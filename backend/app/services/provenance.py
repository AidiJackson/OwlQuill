"""Provenance decision service — the single choke point.

Every route that creates user-visible text calls :func:`decide_provenance` and
none of them decides anything itself. That is the whole architecture: one
function to audit, one place a rule change lands, and no route able to accept a
verdict from its caller.

What the client may and may not influence
-----------------------------------------
Two tiers of evidence, and they are not equal:

* **Server-authoritative.** Whether the surface is an AI tool, and whether the
  submitted text matches something Ficshon's own generators produced for this
  author. Neither is expressible by a client. Both push *toward* AI_ASSISTED.
* **Client-attested.** Composition-session counters. These can only corroborate
  a USER_WRITTEN verdict, never override AI evidence, and are discarded outright
  when they contradict the content the server actually received.

The honest limit: no browser scheme proves a human typed something, and this one
does not claim to. What it does guarantee is that assistance from *Ficshon's own
tools* is labelled regardless of client behaviour, and that "Written in Ficshon"
is backed by a session the server issued rather than applied by default.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from app.models.ai_fingerprint import AIOutputFingerprint
from app.models.composition import CompositionSession
from app.models.provenance import BASE_VERDICTS, Provenance
from app.services import composition as composition_service
from app.services import text_fingerprint

#: Bumped whenever the rules below change meaning. Stamped on every decided row
#: so a later pass can find exactly what a given rule produced and re-evaluate.
RULE_VERSION = 1

#: Where externally-pasted text lands today.
#:
#: Rule v1 routes it to UNKNOWN while recording ``basis: "external_insertion"``
#: in the evidence, so the rows are identifiable. Enabling a distinct public
#: state is this constant plus a client badge entry plus a ``RULE_VERSION`` bump
#: — and a re-decide pass over rows carrying that basis. **No migration**, which
#: is why ``provenance`` is a wide String rather than a database enum.
EXTERNAL_VERDICT = Provenance.UNKNOWN

#: Share of the final text that may arrive by external paste and still count as
#: written here. Non-zero because quoting a line of someone's post, or fixing a
#: sentence via copy-paste inside the editor, is normal writing behaviour.
MAX_EXTERNAL_RATIO = 0.20

#: An AI match needs both a floor and a ratio: the floor stops a handful of
#: coincidental windows in a long post from tripping it, the ratio stops a brief
#: quotation of AI text from relabelling an otherwise original piece.
AI_MATCH_MIN_HASHES = 4
AI_MATCH_MIN_RATIO = 0.15

#: How far back fingerprint matching looks. Bounds the table and reflects that
#: an author reusing their own year-old generation is not what this detects.
FINGERPRINT_RETENTION = timedelta(days=90)

#: Bound-parameter cap per lookup query. Well under SQLite's limit and
#: irrelevant to Postgres.
_LOOKUP_CHUNK = 500


@dataclass(frozen=True)
class ProvenanceDecision:
    """A verdict plus the evidence that produced it."""

    verdict: Provenance
    evidence: dict[str, Any] = field(default_factory=dict)
    rule_version: int = RULE_VERSION
    #: The claimed session, so the caller can link it to the row it produced.
    session: Optional[CompositionSession] = None


#: What the current rules may emit. Derived rather than hardcoded so that
#: flipping ``EXTERNAL_VERDICT`` does not trip the guard meant to help whoever
#: flips it.
EMITTED_VERDICTS = BASE_VERDICTS | {EXTERNAL_VERDICT}


def _decision(
    verdict: Provenance,
    evidence: dict[str, Any],
    session: Optional[CompositionSession] = None,
) -> ProvenanceDecision:
    assert verdict in EMITTED_VERDICTS, f"decision rules must not emit {verdict}"
    return ProvenanceDecision(
        verdict=verdict, evidence=evidence, rule_version=RULE_VERSION, session=session
    )


# ── AI output registration ────────────────────────────────────────────────────

def register_ai_output(
    db: Session,
    *,
    user_id: Optional[int],
    text: str,
    source_kind: str,
    source_ref: Optional[str] = None,
) -> int:
    """Record fingerprints of text a Ficshon generator just produced.

    Called from every generation path. Returns the number of hashes stored —
    zero for output too short to fingerprint, which is not an error.

    Never raises into a generation request: a failure here degrades detection,
    and losing a user's generated chapter to a bookkeeping error would be a far
    worse trade.
    """
    if user_id is None:
        return 0
    hashes = text_fingerprint.fingerprint(text)
    if not hashes:
        return 0

    now = datetime.utcnow()
    for h in set(hashes):
        db.add(
            AIOutputFingerprint(
                user_id=user_id,
                shingle_hash=h,
                source_kind=source_kind,
                source_ref=source_ref,
                created_at=now,
            )
        )
    db.flush()
    return len(set(hashes))


def _match_ai_output(
    db: Session, *, user_id: int, content: str
) -> Optional[dict[str, Any]]:
    """Look for overlap between ``content`` and this author's AI output.

    Author-scoped by design: a post is compared only against generations run by
    its own author, so no user's text is ever evaluated against another's
    private generations.
    """
    hashes = text_fingerprint.fingerprint(content)
    if not hashes:
        return None

    cutoff = datetime.utcnow() - FINGERPRINT_RETENTION
    unique = sorted(set(hashes))

    # Chunked so a long post cannot exceed a backend's bound-parameter limit —
    # SQLite's is low enough to matter, and a silently truncated IN list would
    # mean silently missed detections.
    known: set[int] = set()
    source_kinds: set[str] = set()
    for start in range(0, len(unique), _LOOKUP_CHUNK):
        chunk = unique[start : start + _LOOKUP_CHUNK]
        for row_hash, row_kind in (
            db.query(AIOutputFingerprint.shingle_hash, AIOutputFingerprint.source_kind)
            .filter(
                AIOutputFingerprint.user_id == user_id,
                AIOutputFingerprint.shingle_hash.in_(chunk),
                AIOutputFingerprint.created_at >= cutoff,
            )
            .all()
        ):
            known.add(row_hash)
            source_kinds.add(row_kind)

    if not known:
        return None

    matched, ratio = text_fingerprint.overlap(hashes, known)
    if matched < AI_MATCH_MIN_HASHES or ratio < AI_MATCH_MIN_RATIO:
        return None

    return {
        "basis": "ai_fingerprint",
        "matched_hashes": matched,
        "match_ratio": round(ratio, 3),
        "source_kinds": sorted(source_kinds),
    }


# ── typing evidence ───────────────────────────────────────────────────────────

def _typing_evidence(
    db: Session, session: CompositionSession, content: str
) -> dict[str, Any]:
    """Score a session's counters against the content the server received.

    Returns an evidence dict whose ``basis`` is one of ``composition_session``
    (corroborated), ``inconsistent_metrics`` (the claim contradicts the content)
    or ``external_insertion`` (mostly pasted from outside).
    """
    metrics = session.metrics_json or {}
    typed = int(metrics.get("typed_chars", 0) or 0)
    inserted = int(metrics.get("inserted_chars", 0) or 0)
    claimed_internal = int(metrics.get("internal_insert_chars", 0) or 0)

    length = len(content)
    # Deletions mean the reported totals can exceed the final length, but they
    # can never fall short of it — text the server holds had to arrive somehow.
    # Slack absorbs newline normalisation and IME composition accounting.
    slack = max(16, int(length * 0.02))
    if typed + inserted + slack < length:
        return {
            "basis": "inconsistent_metrics",
            "reported_chars": typed + inserted,
            "content_chars": length,
        }

    internal = composition_service.credited_internal_chars(db, session, claimed_internal)
    external = max(0, inserted - internal)

    # The badge requires *observed* typing, not merely a session that exists.
    # Without this, opening a session and reporting nothing would earn the badge
    # for any post short enough to fit inside the consistency slack — turning
    # "written here" back into something you get by default.
    #
    # Credited internal transfer counts: a WriteSpace draft carried into the
    # composer was typed here, just on the parent session, and the credit is
    # already bounded by what that parent was observed to type.
    if length and typed + internal <= 0:
        return {
            "basis": "no_typing_evidence",
            "session_id": session.id,
            "content_chars": length,
        }

    external_ratio = (external / length) if length else 0.0

    evidence: dict[str, Any] = {
        "session_id": session.id,
        "surface": session.surface,
        "typed_chars": typed,
        "external_chars": external,
        "external_ratio": round(external_ratio, 3),
    }
    if internal:
        evidence["internal_transfer_chars"] = internal

    if external_ratio > MAX_EXTERNAL_RATIO:
        evidence["basis"] = "external_insertion"
    else:
        evidence["basis"] = "composition_session"
    return evidence


# ── the decision ──────────────────────────────────────────────────────────────

def decide_provenance(
    db: Session,
    *,
    user_id: int,
    content: str,
    composition_session_id: Optional[str] = None,
    structural: Optional[Provenance] = None,
    check_ai_fingerprint: bool = True,
) -> ProvenanceDecision:
    """Decide how ``content`` came to exist. The only entry point for routes.

    ``structural`` is passed by surfaces that are AI tools by construction — a
    StoryLab chapter, an accepted generated RP turn. It is a fact about the
    route, not a client input.
    """
    # Claimed first and unconditionally, so a session is spent whether or not it
    # ends up supporting the verdict. Prevents redeeming one session twice by
    # racing an AI-flagged submission against a clean one.
    session = (
        composition_service.claim_session(
            db, user_id=user_id, session_id=composition_session_id
        )
        if composition_session_id
        else None
    )

    if structural is not None:
        return _decision(
            structural, {"basis": "structural_surface"}, session
        )

    if check_ai_fingerprint:
        match = _match_ai_output(db, user_id=user_id, content=content)
        if match:
            if session is not None:
                match["session_id"] = session.id
            return _decision(Provenance.AI_ASSISTED, match, session)

    if session is None:
        # No session: historical clients, direct API use, seeds, backfills.
        # Asserting nothing is the correct answer, and the reason the badge is
        # no longer applied by default.
        return _decision(Provenance.UNKNOWN, {"basis": "no_session"})

    evidence = _typing_evidence(db, session, content)
    basis = evidence["basis"]
    if basis == "composition_session":
        return _decision(Provenance.USER_WRITTEN, evidence, session)
    if basis == "external_insertion":
        return _decision(EXTERNAL_VERDICT, evidence, session)
    return _decision(Provenance.UNKNOWN, evidence, session)


# ── derived content ───────────────────────────────────────────────────────────

#: Worst case wins. A story with one AI-assisted segment is AI-assisted; it is
#: only written-here if every part of it is.
_ROLLUP_PRECEDENCE = (
    Provenance.AI_ASSISTED,
    Provenance.EXTERNAL,
    Provenance.UNKNOWN,
    Provenance.USER_WRITTEN,
)


def inherit(source_provenance: str) -> ProvenanceDecision:
    """Provenance for a row copied verbatim from another — publish, snapshots.

    Carried across rather than recomputed: the copy has no composition session
    of its own, and recomputing would silently downgrade every published story
    to UNKNOWN. This is the hole that ``publish_story`` had.
    """
    try:
        verdict = Provenance(source_provenance)
    except ValueError:
        verdict = Provenance.UNKNOWN
    return ProvenanceDecision(
        verdict=verdict,
        evidence={"basis": "inherited"},
        rule_version=RULE_VERSION,
    )


def rollup(values: Iterable[str]) -> ProvenanceDecision:
    """Collapse many segment verdicts into one for the container."""
    present: set[Provenance] = set()
    for v in values:
        try:
            present.add(Provenance(v))
        except ValueError:
            present.add(Provenance.UNKNOWN)

    if not present:
        return ProvenanceDecision(
            verdict=Provenance.UNKNOWN, evidence={"basis": "empty"}, rule_version=RULE_VERSION
        )

    for candidate in _ROLLUP_PRECEDENCE:
        if candidate in present:
            return ProvenanceDecision(
                verdict=candidate,
                evidence={"basis": "rollup", "segment_states": sorted(p.value for p in present)},
                rule_version=RULE_VERSION,
            )
    return ProvenanceDecision(
        verdict=Provenance.UNKNOWN, evidence={"basis": "rollup"}, rule_version=RULE_VERSION
    )


def external_import(source: str) -> ProvenanceDecision:
    """Text that demonstrably originated outside Ficshon.

    An RP partner's reply pasted in from another platform is the clear case: it
    was not written here by anyone, and calling it user-written would be a lie.
    Resolves to :data:`EXTERNAL_VERDICT` — UNKNOWN today — while recording a
    basis specific enough to re-decide these rows when the state is enabled.
    """
    return ProvenanceDecision(
        verdict=EXTERNAL_VERDICT,
        evidence={"basis": "external_import", "source": source},
        rule_version=RULE_VERSION,
    )


def undecided() -> ProvenanceDecision:
    """Explicit 'we know nothing' — seeds, backfills, imports.

    Used where a route genuinely has no evidence, so the row says so rather than
    inheriting a default that reads as a claim.
    """
    return ProvenanceDecision(
        verdict=Provenance.UNKNOWN, evidence={"basis": "undecided"}, rule_version=RULE_VERSION
    )
