"""The shared record types, and the registry that maps each schema name to its type."""

from __future__ import annotations

from fsi_common.ids import digest_json
from fsi_common.records.base import (
    MACHINE_IDENTITIES,
    MODEL_PRODUCTS,
    Addressed,
    Extractor,
    Person,
    Record,
    SourceRef,
)
from fsi_common.records.briefs import Brief, Statement
from fsi_common.records.carry import CarryOutcome, CarryOver, carry_over, judged_differences
from fsi_common.records.decisions import Assumption, Decision, SignOff
from fsi_common.records.facts import (
    CheckResult,
    ClaimStatus,
    Fact,
    InferenceRule,
    MatchRate,
    Provenance,
    fact_judged_basis,
)
from fsi_common.records.questions import (
    SETTLED_STATES,
    ClaimRef,
    Disagreement,
    GapReason,
    OpenQuestion,
)
from fsi_common.records.sources import Source, SourceUnit, UnitAccounting, UnitWithoutFacts
from fsi_common.records.topic import (
    FACT_TOPIC_CONTEXT_KEY,
    FactTopic,
    fact_id_basis,
    fact_topic,
    fact_topic_context,
)

RECORD_TYPES: dict[str, type[Record]] = {
    cls.SCHEMA: cls
    for cls in (
        Source,
        SourceUnit,
        Fact,
        OpenQuestion,
        Disagreement,
        Decision,
        Brief,
        SignOff,
        UnitAccounting,
    )
}
"""Every top-level record type, keyed by the schema name its JSON carries in ``schema``."""


def record_digest(record: Addressed) -> str:
    """Return the digest of a whole record as a person is shown it.

    A decision carries this digest as ``seen_digest``, so a decision on a record that has since
    changed no longer matches it.

    Args:
        record: Any record, or a statement of a brief.

    Returns:
        The digest of the record's canonical JSON.
    """
    return digest_json(record.to_json())


def judged_digest(record: Addressed) -> str:
    """Return the digest of what a person judges in a record.

    A decision carries this digest as ``judged_digest``. For a fact it covers the kind, subject,
    quote, attributes and each check's name and outcome, so a rerun with another model, prompt,
    extractor or check wording gives the same digest and the decision carries over.

    Args:
        record: Any record, or a statement of a brief.

    Returns:
        The digest of the record's judged fields.
    """
    return digest_json(record.judged_basis())


__all__ = [
    "MACHINE_IDENTITIES",
    "MODEL_PRODUCTS",
    "RECORD_TYPES",
    "SETTLED_STATES",
    "Addressed",
    "Assumption",
    "Brief",
    "CarryOutcome",
    "CarryOver",
    "CheckResult",
    "ClaimRef",
    "ClaimStatus",
    "Decision",
    "Disagreement",
    "Extractor",
    "FACT_TOPIC_CONTEXT_KEY",
    "Fact",
    "FactTopic",
    "GapReason",
    "InferenceRule",
    "MatchRate",
    "OpenQuestion",
    "Person",
    "Provenance",
    "Record",
    "SignOff",
    "Source",
    "SourceRef",
    "SourceUnit",
    "Statement",
    "UnitAccounting",
    "UnitWithoutFacts",
    "carry_over",
    "fact_id_basis",
    "fact_judged_basis",
    "fact_topic",
    "fact_topic_context",
    "judged_differences",
    "judged_digest",
    "record_digest",
]
