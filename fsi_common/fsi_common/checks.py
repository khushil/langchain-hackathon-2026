"""The named checks the validator runs, and the check of one record at a time."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from fsi_common.records import RECORD_TYPES, Fact, Record, fact_kinds_context

ALL = frozenset(RECORD_TYPES)
BUNDLE = "bundle"


@dataclass(frozen=True)
class Finding:
    """One failed check: which check, where, and what it found."""

    check: str
    where: str
    message: str


@dataclass(frozen=True)
class CheckInfo:
    """What a check covers: the record schemas it applies to, or bundles."""

    description: str
    applies_to: frozenset[str]


def _on(*schemas: str) -> frozenset[str]:
    return frozenset(schemas)


CHECKS: dict[str, CheckInfo] = {
    "schema.unknown": CheckInfo("the record names a schema this package defines", ALL),
    "schema.required": CheckInfo("every required field is present", ALL),
    "schema.enum": CheckInfo("every closed-list field holds a value from its list", ALL),
    "schema.extra": CheckInfo("no field outside the schema", ALL),
    "schema.type": CheckInfo("every field has its type, pattern and bounds", ALL),
    "schema.date": CheckInfo("every date is a calendar date", ALL),
    "id.recompute": CheckInfo("every id recomputes from its record's content", ALL),
    "fact.quote": CheckInfo("every fact quotes its source unit", _on("fact.v1")),
    "fact.kind": CheckInfo("every fact's kind is in the topic's closed list", _on("fact.v1")),
    "fact.provenance-subject": CheckInfo(
        "a fact's provenance names its own subject", _on("fact.v1")
    ),
    "provenance.model-pair": CheckInfo(
        "model and prompt version are given together", _on("fact.v1")
    ),
    "status.observed": CheckInfo("an observed claim says when it was read", _on("fact.v1")),
    "status.inferred": CheckInfo("an inferred claim names its rule", _on("fact.v1")),
    "status.unknown": CheckInfo("an unknown claim says why", _on("fact.v1")),
    "status.extra": CheckInfo("a claim carries only its own status's fields", _on("fact.v1")),
    "status.match-rate": CheckInfo("a rule's matches do not exceed its population", _on("fact.v1")),
    "person.empty": CheckInfo("a reviewer has a name and a role", _on("decision.v1", "signoff.v1")),
    "person.machine": CheckInfo(
        "a reviewer is never a model or a program", _on("decision.v1", "signoff.v1")
    ),
    "decision.outcome": CheckInfo("a decision's outcome fits its subject", _on("decision.v1")),
    "question.cites": CheckInfo("a question cites what it rests on", _on("open_question.v1")),
    "question.state": CheckInfo(
        "a settled question names a person's decision", _on("open_question.v1")
    ),
    "disagreement.claims": CheckInfo(
        "a disagreement keeps two or more facts", _on("disagreement.v1")
    ),
    "disagreement.status": CheckInfo("only a person's decision reconciles", _on("disagreement.v1")),
    "brief.statement-cites": CheckInfo("every statement cites a fact", _on("brief.v1")),
    "digest.recompute": CheckInfo("a brief's digest recomputes from its content", _on("brief.v1")),
    "signoff.reason": CheckInfo("a returned brief says why", _on("signoff.v1")),
    "signoff.assumptions": CheckInfo("no question is accepted twice", _on("signoff.v1")),
    "accounting.empty": CheckInfo(
        "a source was read into at least one unit", _on("unit_accounting.v1")
    ),
    "accounting.closes": CheckInfo(
        "units in equal units with and without facts", _on("unit_accounting.v1")
    ),
    "id.duplicate": CheckInfo("no id names two different records", _on(BUNDLE)),
    "ref.resolves": CheckInfo("every id a record cites is in the bundle", _on(BUNDLE)),
    "decision.digest-stale": CheckInfo("a decision's digest is its subject's", _on(BUNDLE)),
    "question.decision-matches": CheckInfo(
        "a settled question's decision is about it", _on(BUNDLE)
    ),
    "brief.cites-failed-check": CheckInfo(
        "no statement cites a fact that failed a check", _on(BUNDLE)
    ),
    "signoff.digest-matches": CheckInfo("a sign-off's digest is its brief's", _on(BUNDLE)),
    "signoff.open-question-unrecorded": CheckInfo(
        "a signed brief's open questions are settled or accepted as assumptions", _on(BUNDLE)
    ),
    "accounting.facts-match": CheckInfo(
        "the units with facts are those the facts cite", _on(BUNDLE)
    ),
}
"""Every check by id. The validator counts, for each check, the records or bundles it examined."""

_PYDANTIC_TYPES = {
    "missing": "schema.required",
    "literal_error": "schema.enum",
    "enum": "schema.enum",
    "extra_forbidden": "schema.extra",
}


def check_for_error(error_type: str) -> str:
    """Map a validation error's type to the check it belongs to.

    Args:
        error_type: The ``type`` of a pydantic error.

    Returns:
        The check id: the error type itself for this package's own checks, else a ``schema.`` check.
    """
    if "." in error_type:
        return error_type
    return _PYDANTIC_TYPES.get(error_type, "schema.type")


def validate_record(
    data: Any, *, where: str, fact_kinds: frozenset[str] | None
) -> tuple[Record | None, list[Finding]]:
    """Validate one record read from JSON.

    Args:
        data: The JSON value read.
        where: Where it was read from, for the findings.
        fact_kinds: The topic's closed list of fact kinds; a fact read without one fails
            ``fact.kind``.

    Returns:
        The record, or None if it failed, and the findings.
    """
    if not isinstance(data, dict) or data.get("schema") not in RECORD_TYPES:
        name = data.get("schema") if isinstance(data, dict) else type(data).__name__
        return None, [Finding("schema.unknown", where, f"'{name}' is not a record schema")]
    record_type = RECORD_TYPES[data["schema"]]
    if record_type is Fact and fact_kinds is None:
        return None, [Finding("fact.kind", where, "no closed list of fact kinds was given")]
    context = fact_kinds_context(fact_kinds) if fact_kinds is not None else None
    try:
        record = record_type.model_validate(data, context=context)
    except ValidationError as exc:
        findings = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"])
            findings.append(
                Finding(check_for_error(error["type"]), f"{where} {location}".strip(), error["msg"])
            )
        return None, findings
    return record, []
