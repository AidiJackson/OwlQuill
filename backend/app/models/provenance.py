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

    ``EXTERNAL`` is declared but **never emitted by rule version 1**. It is the
    reserved landing place for text pasted in from outside Ficshon, which today
    resolves to ``UNKNOWN`` while carrying ``basis: "external_insertion"`` in its
    evidence. Promoting it is a one-constant change in the service plus a badge
    entry in the client — see ``app.services.provenance.EXTERNAL_VERDICT``.
    """

    USER_WRITTEN = "user_written"
    AI_ASSISTED = "ai_assisted"
    UNKNOWN = "unknown"
    EXTERNAL = "external"


#: The states the decision rules always produce, whatever the external verdict
#: is configured to be. ``app.services.provenance`` adds ``EXTERNAL_VERDICT`` to
#: this to form its own guard, so promoting the external state stays a
#: one-constant change rather than tripping an assertion.
BASE_VERDICTS = frozenset(
    {Provenance.USER_WRITTEN, Provenance.AI_ASSISTED, Provenance.UNKNOWN}
)


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
