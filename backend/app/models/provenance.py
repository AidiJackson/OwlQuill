"""Content provenance — evidence-based authorship state for user-visible text.

The public badge ("Written in Ficshon" / "AI Assisted") is derived from these
columns and from nothing else. The vocabulary and the decision live in
``app.services.provenance``; this module owns only the storage shape.

Design notes
------------
``provenance`` is a plain ``String``, not ``SQLEnum``, and is sized well beyond
the longest value in use. Adding a state — the planned ``external`` /
``imported`` verdict is the near-term case — is therefore a Python + UI change
with **no migration**. This is deliberate: the state set is expected to grow and
the schema must not be the thing that makes growing it expensive.

``provenance_rule_version`` defaults to ``0``, meaning *never evaluated*. Rows
written before this sprint, and rows created by paths that do not yet decide,
keep ``0`` and are honestly reported as unknown. Only a row that went through
``decide_provenance`` carries a non-zero version, so a future rule change can
find and re-evaluate exactly the rows a given rule produced.
"""
from datetime import datetime
import enum

from sqlalchemy import Column, DateTime, SmallInteger, String
from sqlalchemy.types import JSON


class Provenance(str, enum.Enum):
    """How a piece of user-visible text came to exist.

    Three states are user-facing, and the product philosophy behind them is that
    Ficshon states what it *knows* rather than guessing what it does not:

    * ``USER_WRITTEN`` — Ficshon observed the text being composed here.
    * ``AI_ASSISTED``  — Ficshon's own AI tools produced or substantially
      assisted it.
    * ``EXTERNAL``     — everything else. "Created elsewhere" is a statement
      about where the content was created, **not** a claim that the text is
      AI-written. Notepad, Word, Docs, Discord, an imported roleplay log, a
      translation, an archived post and an outside AI all land here alike,
      because Ficshon cannot tell them apart and does not pretend to.

    ``UNKNOWN`` is **legacy only**. It is what rows created before the
    provenance system carry, and the rules no longer emit it. It is retained so
    those rows stay identifiable as never-evaluated (``rule_version = 0``); the
    client displays them as "Created elsewhere" like any other content Ficshon
    did not observe being created here.
    """

    USER_WRITTEN = "user_written"
    AI_ASSISTED = "ai_assisted"
    EXTERNAL = "external"
    #: Legacy — pre-provenance rows. Never emitted by the rules.
    UNKNOWN = "unknown"


#: The states the decision rules always produce, whatever the external verdict
#: is configured to be. ``app.services.provenance`` adds ``EXTERNAL_VERDICT`` to
#: this to form its own guard, so changing where "not written here" lands stays
#: a one-constant change rather than tripping an assertion.
#:
#: ``UNKNOWN`` is deliberately absent: a decision that cannot prove anything now
#: resolves to EXTERNAL, so nothing the rules produce is ever unbadged.
BASE_VERDICTS = frozenset({Provenance.USER_WRITTEN, Provenance.AI_ASSISTED})


class ProvenanceMixin:
    """Inline provenance columns, mixed into every table holding public text.

    Inline rather than a polymorphic side table so the verdict is written by the
    same ``INSERT`` as the content it describes: a content row without a verdict
    is not representable, and no read path needs a join to render the badge.
    """

    provenance = Column(
        String(32),
        nullable=False,
        default=Provenance.UNKNOWN.value,
        server_default=Provenance.UNKNOWN.value,
    )
    #: Compact, decided server-side. Small and fixed-shape by design — anything
    #: that needs to grow belongs in a side table, not here.
    provenance_evidence = Column(JSON, nullable=True)
    provenance_rule_version = Column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    provenance_decided_at = Column(DateTime, nullable=True)

    def apply_provenance(self, decision) -> None:
        """Stamp a :class:`~app.services.provenance.ProvenanceDecision` onto this row.

        The only supported way to set provenance. Keeps the four columns
        consistent with each other — a verdict can never be written without the
        evidence and rule version that produced it.
        """
        self.provenance = decision.verdict.value
        self.provenance_evidence = decision.evidence
        self.provenance_rule_version = decision.rule_version
        self.provenance_decided_at = datetime.utcnow()
