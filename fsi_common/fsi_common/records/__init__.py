"""The shared record types, and the registry that maps each schema name to its type."""

from __future__ import annotations

from collections.abc import Iterable

from fsi_common.ids import digest_json
from fsi_common.records.base import MACHINE_WORDS, Addressed, Extractor, Person, Record, SourceRef
from fsi_common.records.briefs import Brief, Statement
from fsi_common.records.decisions import Assumption, Decision, SignOff
from fsi_common.records.facts import (
    FACT_KINDS_CONTEXT_KEY,
    CheckResult,
    ClaimStatus,
    Fact,
    InferenceRule,
    MatchRate,
    Provenance,
)
from fsi_common.records.questions import SETTLED_STATES, Disagreement, GapReason, OpenQuestion
from fsi_common.records.sources import Source, SourceUnit, UnitAccounting, UnitWithoutFacts

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


def fact_kinds_context(kinds: Iterable[str]) -> dict[str, frozenset[str]]:
    """Return the validation context that holds a topic's closed list of fact kinds.

    Args:
        kinds: The topic's fact kinds.

    Returns:
        A context to pass to ``Fact.build`` or ``Fact.model_validate``.
    """
    return {FACT_KINDS_CONTEXT_KEY: frozenset(kinds)}


__all__ = [
    "MACHINE_WORDS",
    "RECORD_TYPES",
    "SETTLED_STATES",
    "Addressed",
    "Assumption",
    "Brief",
    "CheckResult",
    "ClaimStatus",
    "Decision",
    "Disagreement",
    "Extractor",
    "Fact",
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
    "fact_kinds_context",
    "record_digest",
]
