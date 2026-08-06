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

Three outcomes, and only three
------------------------------
State what we know; do not guess what we do not. A piece of text either was
observed being composed here, or was produced by our own AI, or was not composed
here — and the third case is a single state on purpose. Ficshon cannot tell a
Notepad paste from a Word paste from an outside AI, so it does not try, and
"Written elsewhere" makes no claim about which it was.

There is consequently no "we have no idea" outcome. Anything that fails to earn
USER_WRITTEN and carries no AI evidence is EXTERNAL, because "we did not observe
you writing this here" is itself something we know.
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
#:
#: v2 — "Written elsewhere" became a real state. Every outcome that previously
#: resolved to UNKNOWN (no session, unusable metrics, no observed typing, mostly
#: pasted) now resolves to EXTERNAL, so a decided row is never unbadged.
RULE_VERSION = 2

#: Where content Ficshon did not observe being written here lands.
#:
#: This is a positive, honest statement — "not composed in Ficshon" — and
#: explicitly **not** a claim about AI. Text from Notepad, Word, Docs, Discord,
#: an old RP site or an outside AI are indistinguishable to us, so they share
#: one state rather than being guessed apart.
#:
#: Still a single constant: the schema is a wide String, not a database enum, so
#: moving where this lands remains a code change with no migration.
EXTERNAL_VERDICT = Provenance.EXTERNAL

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

    Exactly one ``basis`` earns USER_WRITTEN — ``composition_session``. Every
    other outcome means Ficshon did not observe the text being written here, so
    it resolves to EXTERNAL. The distinct bases are kept for diagnostics and for
    future rule versions, not because they lead anywhere different today:

    * ``composition_session``  — corroborated typing. The only one that earns it.
    * ``inconsistent_metrics`` — the client's claim contradicts the content.
    * ``no_typing_evidence``   — a session exists but nothing was typed into it.
    * ``external_insertion``   — mostly arrived by paste or drop.
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
        # No session: older clients, direct API use, seeds, imports. Ficshon did
        # not watch this being written, which is itself a fact worth stating.
        return _decision(EXTERNAL_VERDICT, {"basis": "no_session"})

    evidence = _typing_evidence(db, session, content)
    basis = evidence["basis"]
    if basis == "composition_session":
        return _decision(Provenance.USER_WRITTEN, evidence, session)
    # Everything else — pasted in, unusable metrics, nothing typed — is content
    # Ficshon did not observe being written here. One state, no guessing at
    # which kind of elsewhere it came from.
    return _decision(EXTERNAL_VERDICT, evidence, session)


# ── derived content ───────────────────────────────────────────────────────────

#: Weakest claim wins. A story with one AI-assisted segment is AI-assisted; it
#: is only written-here if every part of it is. Legacy UNKNOWN segments sit with
#: EXTERNAL because they make the same public statement.
_ROLLUP_PRECEDENCE = (
    Provenance.AI_ASSISTED,
    Provenance.EXTERNAL,
    Provenance.UNKNOWN,
    Provenance.USER_WRITTEN,
)


def inherit(source_provenance: str) -> ProvenanceDecision:
    """Provenance for a row copied verbatim from another — publish, snapshots.

    Carried across rather than recomputed: the copy has no composition session
    of its own, and recomputing would downgrade every published story to
    EXTERNAL. This is the hole that ``publish_story`` had.
    """
    try:
        verdict = Provenance(source_provenance)
    except ValueError:
        verdict = EXTERNAL_VERDICT
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
            present.add(EXTERNAL_VERDICT)

    if not present:
        return ProvenanceDecision(
            verdict=EXTERNAL_VERDICT, evidence={"basis": "empty"}, rule_version=RULE_VERSION
        )

    for candidate in _ROLLUP_PRECEDENCE:
        if candidate in present:
            return ProvenanceDecision(
                verdict=candidate,
                evidence={"basis": "rollup", "segment_states": sorted(p.value for p in present)},
                rule_version=RULE_VERSION,
            )
    return ProvenanceDecision(
        verdict=EXTERNAL_VERDICT, evidence={"basis": "rollup"}, rule_version=RULE_VERSION
    )


def external_import(source: str) -> ProvenanceDecision:
    """Text that demonstrably originated outside Ficshon.

    An RP partner's reply pasted in from another platform is the clear case: it
    was not written here by anyone, and calling it written-in-Ficshon would be a
    lie. The ``source`` is recorded for diagnostics only — the public statement
    is the same "Written elsewhere" every other external route produces.
    """
    return ProvenanceDecision(
        verdict=EXTERNAL_VERDICT,
        evidence={"basis": "external_import", "source": source},
        rule_version=RULE_VERSION,
    )


def not_composed_here(reason: str = "seeded") -> ProvenanceDecision:
    """Content that entered Ficshon without passing through its composer.

    Editorial seed posts and imports. Ficshon did not watch anyone write these,
    so they carry the same honest statement as any other outside text — rather
    than a default that reads as a claim, which is what the old badge did.
    """
    return ProvenanceDecision(
        verdict=EXTERNAL_VERDICT,
        evidence={"basis": "not_composed_here", "reason": reason},
        rule_version=RULE_VERSION,
    )
