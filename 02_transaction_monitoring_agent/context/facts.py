"""Turn a customer's profile row and the assessor's recorded proposals into facts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from context.checks import (
    RecordedAssessment,
    assessment_checks,
    assessment_quote,
    check_quote,
)
from context.errors import AssessmentReadError
from context.reader import StreamRead
from fsi_common.records import Extractor, Fact
from utils.records import COPIED_ATTRIBUTES, FACT_CONTEXT, customer_anchor, transaction_anchor

PROFILE_READER = Extractor(name="profile-reader", version="0.1.0")
"""The step that turns a profile row into facts; code, so its facts name no model."""

ASSESSOR = Extractor(name="transaction-assessor", version="0.1.0")
"""The step that turns the starter's agent's recorded proposal into a fact."""

PROFILE_FIELDS = (
    "name",
    "home_country",
    "city",
    "currency",
    "usual_amount_range",
    "usual_categories",
    "customer_since",
)


def _field_quote(field: str, value: Any) -> str:
    return f'"{field}": {json.dumps(value, ensure_ascii=False)}'


def customer_facts(stream: StreamRead) -> list[Fact]:
    """Read the customer's profile row into one fact for each of its fields.

    A quote is the field as the row writes it, and the quote check runs on every fact.

    Args:
        stream: The stream read, which holds the profile row and its unit.

    Returns:
        The facts, in the order of ``PROFILE_FIELDS``.
    """
    anchor = customer_anchor(stream.user_id)
    unit = stream.unit_of[anchor]
    text = stream.unit_text[unit.id]
    source = stream.profile_source
    facts = []
    for field in PROFILE_FIELDS:
        value = stream.profile[field]
        quote = _field_quote(field, value)
        if field == "usual_amount_range":
            attributes: dict[str, Any] = {"field": field, "low": value[0], "high": value[1]}
        else:
            attributes = {"field": field, "value": value}
        facts.append(
            Fact.build(
                context=FACT_CONTEXT,
                kind="customer_attribute",
                subject={"source_id": source.id, "anchor": anchor},
                quote=quote,
                attributes=attributes,
                status={"status": "documented"},
                provenance={
                    "source_id": source.id,
                    "anchor": anchor,
                    "extractor": PROFILE_READER,
                    "as_of": source.digest,
                },
                checks=[check_quote(quote, text, anchor=anchor)],
            )
        )
    return facts


def _kept(value: Any) -> Any:
    """Return a value as a fact attribute holds it: whole numbers, flags, text and none as given."""
    if value is None or isinstance(value, bool | int | str):
        return value
    return repr(value)


def assessment_fact(
    stream: StreamRead,
    row: Mapping[str, Any],
    recorded: RecordedAssessment,
    *,
    model: str,
    prompt_version: str,
    observed_on: str,
) -> Fact:
    """Turn the proposal the starter's agent recorded for a transaction into a fact.

    The quote is the transaction's own field values, and every plain-code check runs on the fact.
    A proposal that fails a check stays a fact with the failed check on it: nothing is dropped.

    Args:
        stream: The stream read, which holds the transaction's unit.
        row: The transaction's row.
        recorded: The proposal the assessor recorded.
        model: The model that made it.
        prompt_version: The version of the prompt it was asked with.
        observed_on: The date the proposal was recorded, as ``YYYY-MM-DD``.

    Returns:
        A fact of kind ``transaction_assessment`` about the transaction.

    Raises:
        AssessmentReadError: If the proposal is for another transaction than the row.
    """
    if recorded.transaction_id != row["transaction_id"]:
        raise AssessmentReadError(
            f"The proposal is for {recorded.transaction_id}, and the row is "
            f"{row['transaction_id']}."
        )
    anchor = transaction_anchor(row["transaction_id"])
    unit = stream.unit_of[anchor]
    quote = assessment_quote(row)
    attributes: dict[str, Any] = {
        name: _kept(row[name]) if name != "amount" else str(row[name]) for name in COPIED_ATTRIBUTES
    }
    attributes.update(
        risk_score=_kept(recorded.risk_score),
        proposed_decision=_kept(recorded.agent_decision),
        confidence=str(recorded.confidence),
        model_confidence=str(recorded.model_confidence),
        confidence_checks=[str(reason) for reason in recorded.confidence_checks],
        reason=str(recorded.reason),
    )
    source = stream.transaction_source
    return Fact.build(
        context=FACT_CONTEXT,
        kind="transaction_assessment",
        subject={"source_id": source.id, "anchor": anchor},
        quote=quote,
        attributes=attributes,
        status={"status": "observed", "observed_at": observed_on},
        provenance={
            "source_id": source.id,
            "anchor": anchor,
            "extractor": ASSESSOR,
            "model": model,
            "prompt_version": prompt_version,
            "as_of": source.digest,
        },
        checks=assessment_checks(row, stream.unit_text[unit.id], quote, recorded),
    )
