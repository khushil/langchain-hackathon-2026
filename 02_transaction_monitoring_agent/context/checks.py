"""The plain-code checks on an assessment: the quote, the score, the decision and the confidence."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from context.errors import AssessmentReadError
from context.text import contains_word_for_word
from fsi_common.records import CheckResult
from tools.decisions import _confidence_checks
from utils.state import MyAgentContext

QUOTE_CHECK = "quote-verbatim.v1"
FIELDS_CHECK = "fields-in-row.v1"
SCORE_CHECK = "score-in-range.v1"
DECISION_CHECK = "decision-follows-score.v1"
CONFIDENCE_RANGE_CHECK = "confidence-in-range.v1"
CONFIDENCE_CHECKS_CHECK = "confidence-checks.v1"
CHECK_NAMES = (
    QUOTE_CHECK,
    FIELDS_CHECK,
    SCORE_CHECK,
    DECISION_CHECK,
    CONFIDENCE_RANGE_CHECK,
    CONFIDENCE_CHECKS_CHECK,
)
"""Every check an assessment fact is run through, in the order its results are recorded."""

_SETTINGS = MyAgentContext()
GREY_ZONE = _SETTINGS.grey_zone
BLOCK_FROM = GREY_ZONE[1]
"""The starter's own rule: a score from 70 up is blocked, and one from 30 to 69 is the grey zone."""
CHECKED_CONFIDENCE = _SETTINGS.checked_confidence
DECISIONS = ("approve", "block")
_AUDIT_FIELDS = (
    "transaction_id",
    "risk_score",
    "model_confidence",
    "confidence",
    "confidence_checks",
    "agent_decision",
    "reason",
)


@dataclass(frozen=True)
class RecordedAssessment:
    """What the starter's ``record_decision`` kept about one transaction, as a proposal.

    The audit record also says who decided; that is not read here, because in this topic the
    agent only proposes, and a named person decides.
    """

    transaction_id: str
    risk_score: Any
    model_confidence: Any
    confidence: Any
    confidence_checks: list[str]
    agent_decision: Any
    reason: str

    @classmethod
    def from_audit(cls, audit: Mapping[str, Any]) -> RecordedAssessment:
        """Read the proposal out of the starter's audit record.

        Args:
            audit: The record ``record_decision`` puts in the store under ``("decisions", user)``.

        Returns:
            The proposal, with the audit record's ``final_decision`` and ``decided_by`` left out.

        Raises:
            AssessmentReadError: If the record lacks a field the checks read; each is named.
        """
        missing = [name for name in _AUDIT_FIELDS if name not in audit]
        if missing:
            raise AssessmentReadError(
                f"The recorded assessment lacks {', '.join(missing)}: {dict(audit)}"
            )
        return cls(**{name: audit[name] for name in _AUDIT_FIELDS})


def assessment_quote(row: Mapping[str, Any]) -> str:
    """Return the quote an assessment of a transaction carries: the row's own field values.

    Args:
        row: The transaction's row.

    Returns:
        Every field of the row after its id, as the data file writes them, for example
        ``"user_id": "USR-001", "timestamp": "2026-10-09T21:03", ...``.
    """
    return ", ".join(
        f'"{key}": {json.dumps(value, ensure_ascii=False)}'
        for key, value in row.items()
        if key != "transaction_id"
    )


def _is_whole_number(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_confidence(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= 1
    )


def check_quote(quote: str, unit_text: str | None, *, anchor: str) -> CheckResult:
    """Check that a quote is word for word in the unit it cites.

    Args:
        quote: The quote.
        unit_text: The unit's line of its data file, or None when the unit was not found.
        anchor: The unit's anchor, for the detail.

    Returns:
        A ``quote-verbatim.v1`` result saying what was compared and what was found.
    """
    if unit_text is None:
        return CheckResult(
            check=QUOTE_CHECK, outcome="fail", detail=f"there is no unit {anchor} to compare with"
        )
    if contains_word_for_word(quote, unit_text):
        return CheckResult(
            check=QUOTE_CHECK, outcome="pass", detail=f"found word for word in {anchor}"
        )
    return CheckResult(
        check=QUOTE_CHECK,
        outcome="fail",
        detail=f"'{quote}' is not found word for word in {anchor}",
    )


def check_fields(quote: str, row: Mapping[str, Any]) -> CheckResult:
    """Check that every field a quote names is in the row with that value.

    Args:
        quote: The quote, as ``"field": value`` pairs separated by commas.
        row: The transaction's row.

    Returns:
        A ``fields-in-row.v1`` result naming each field that is missing or differs.
    """
    try:
        named = json.loads("{" + quote + "}")
    except ValueError:
        return CheckResult(
            check=FIELDS_CHECK,
            outcome="fail",
            detail=f"the quote '{quote}' does not read as field names and values",
        )
    wrong = [key for key, value in named.items() if key not in row or row[key] != value]
    if wrong:
        return CheckResult(
            check=FIELDS_CHECK,
            outcome="fail",
            detail=f"the quote names {', '.join(wrong)}, which the row lacks with that value",
        )
    return CheckResult(
        check=FIELDS_CHECK,
        outcome="pass",
        detail=f"{len(named)} of {len(named)} fields of the quote are in the row with that value",
    )


def check_score(score: Any) -> CheckResult:
    """Check that a risk score is a whole number from 0 to 100.

    Args:
        score: The score the assessor recorded.

    Returns:
        A ``score-in-range.v1`` result.
    """
    if _is_whole_number(score) and 0 <= score <= 100:
        return CheckResult(
            check=SCORE_CHECK, outcome="pass", detail=f"{score} is a whole number from 0 to 100"
        )
    return CheckResult(
        check=SCORE_CHECK,
        outcome="fail",
        detail=f"{score!r} is not a whole number from 0 to 100",
    )


def check_decision(score: Any, decision: Any) -> CheckResult:
    """Check that the proposed decision follows the starter's rule for the score.

    The starter blocks from a score of 70 and approves below it; the analysts' labels follow the
    same rule in every row.

    Args:
        score: The score the assessor recorded.
        decision: The decision it proposed.

    Returns:
        A ``decision-follows-score.v1`` result.
    """
    if decision not in DECISIONS:
        return CheckResult(
            check=DECISION_CHECK,
            outcome="fail",
            detail=f"{decision!r} is neither approve nor block",
        )
    if not _is_whole_number(score):
        return CheckResult(
            check=DECISION_CHECK,
            outcome="fail",
            detail=f"the score {score!r} is not a whole number, so the rule cannot be applied",
        )
    expected = "block" if score >= BLOCK_FROM else "approve"
    if decision == expected:
        return CheckResult(
            check=DECISION_CHECK,
            outcome="pass",
            detail=f"{decision} is what the starter's rule gives for a score of {score} "
            f"(block from {BLOCK_FROM})",
        )
    return CheckResult(
        check=DECISION_CHECK,
        outcome="fail",
        detail=f"{decision} was proposed for a score of {score}, where the starter's rule gives "
        f"{expected} (block from {BLOCK_FROM})",
    )


def check_confidence_range(model_confidence: Any, confidence: Any) -> CheckResult:
    """Check that both confidences, the model's own and the one kept, lie from 0 to 1.

    Args:
        model_confidence: The confidence the model gave.
        confidence: The confidence kept after the starter's checks.

    Returns:
        A ``confidence-in-range.v1`` result.
    """
    if _is_confidence(model_confidence) and _is_confidence(confidence):
        return CheckResult(
            check=CONFIDENCE_RANGE_CHECK,
            outcome="pass",
            detail=f"{model_confidence} and {confidence} both lie from 0 to 1",
        )
    return CheckResult(
        check=CONFIDENCE_RANGE_CHECK,
        outcome="fail",
        detail=f"{model_confidence!r} and {confidence!r} do not both lie from 0 to 1",
    )


def check_confidence_checks(
    recorded: RecordedAssessment, row: Mapping[str, Any], user_id: str
) -> CheckResult:
    """Run the starter's own confidence checks again and compare them with what was recorded.

    The starter's checks (a score in the grey zone, a payment abroad above the customer's usual
    maximum) can only lower the confidence. This check recomputes them from the row and the
    score, and requires the recorded reasons to be the same and the recorded confidence to be
    what the starter's rule gives: the model's own, or at most the checked confidence when a
    check fired.

    Args:
        recorded: The proposal the assessor recorded.
        row: The transaction's row.
        user_id: The customer.

    Returns:
        A ``confidence-checks.v1`` result.
    """
    if not (_is_whole_number(recorded.risk_score) and _is_confidence(recorded.model_confidence)):
        return CheckResult(
            check=CONFIDENCE_CHECKS_CHECK,
            outcome="fail",
            detail="the starter's checks cannot be run again on a score or confidence that is "
            "not a number in range",
        )
    fired = _confidence_checks(recorded.risk_score, dict(row), user_id, GREY_ZONE)
    expected = (
        min(recorded.model_confidence, CHECKED_CONFIDENCE) if fired else recorded.model_confidence
    )
    said = "; ".join(fired) if fired else "none fired"
    if list(recorded.confidence_checks) != fired:
        return CheckResult(
            check=CONFIDENCE_CHECKS_CHECK,
            outcome="fail",
            detail=f"the starter's checks give {said}, and {recorded.confidence_checks} was "
            "recorded",
        )
    if not _is_confidence(recorded.confidence) or not math.isclose(
        recorded.confidence, expected, abs_tol=1e-9
    ):
        return CheckResult(
            check=CONFIDENCE_CHECKS_CHECK,
            outcome="fail",
            detail=f"the starter's checks ({said}) give a confidence of {expected}, and "
            f"{recorded.confidence} was recorded",
        )
    return CheckResult(
        check=CONFIDENCE_CHECKS_CHECK,
        outcome="pass",
        detail=f"the starter's checks give {said}, and the confidence {recorded.confidence} is "
        "what they give",
    )


def assessment_checks(
    row: Mapping[str, Any], unit_text: str | None, quote: str, recorded: RecordedAssessment
) -> list[CheckResult]:
    """Run every check an assessment fact is due, in the order of ``CHECK_NAMES``.

    Args:
        row: The transaction's row.
        unit_text: The transaction's line of its data file.
        quote: The quote the fact carries.
        recorded: The proposal the assessor recorded.

    Returns:
        One result for each check.
    """
    anchor = f"tx:{row['transaction_id']}"
    return [
        check_quote(quote, unit_text, anchor=anchor),
        check_fields(quote, row),
        check_score(recorded.risk_score),
        check_decision(recorded.risk_score, recorded.agent_decision),
        check_confidence_range(recorded.model_confidence, recorded.confidence),
        check_confidence_checks(recorded, row, row["user_id"]),
    ]
