"""Open questions for the transactions a person must decide with no usable assessment to read."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fsi_common.records import Fact, OpenQuestion, SourceUnit

ASK_ROLE = "Fraud analyst"
SETTLING_CHECKS = ("decision-follows-score.v1", "confidence-checks.v1")
"""The checks whose failure means the assessment contradicts itself, not that it cannot be read."""


def _what(row: Mapping[str, Any]) -> str:
    return (
        f"{row['transaction_id']} ({row['merchant']}, {row['amount']} {row['currency']} "
        f"in {row['country']})"
    )


def question_for_failed(fact: Fact, unit: SourceUnit, row: Mapping[str, Any]) -> OpenQuestion:
    """Ask about a transaction whose assessment failed a plain-code check.

    The assessment stays on the record with the failed check, and stays off the brief; the
    question carries the transaction to the reviewer instead, so nothing is decided by default.

    Args:
        fact: The assessment fact, with at least one failed check.
        unit: The transaction's unit.
        row: The transaction's row.

    Returns:
        An open question for a fraud analyst. Its reason is ``contradiction`` when the assessment
        disagrees with itself (the decision with the score, the confidence with the starter's
        checks) and ``unreadable`` when a number is out of range or does not read.
    """
    failed = [c for c in fact.checks if c.outcome == "fail"]
    contradiction = all(c.check in SETTLING_CHECKS for c in failed)
    said = (
        f"proposed {fact.attributes['proposed_decision']} with a risk score of "
        f"{fact.attributes['risk_score']}"
    )
    return OpenQuestion.build(
        about={"source_id": fact.subject.source_id, "anchor": fact.subject.anchor},
        question=(
            f"The assessment of {_what(row)} did not pass every check. "
            "Should the payment be approved or blocked?"
        ),
        why_unknown=(
            f"The assessor {said}. These checks failed: "
            + "; ".join(f"{c.check}: {c.detail}" for c in failed)
            + "."
        ),
        impact="Until a person decides, the transaction is not on the brief, and the proposal "
        "is not used.",
        ask_role=ASK_ROLE,
        reason="contradiction" if contradiction else "unreadable",
        cites=[fact.id, unit.id],
        priority="medium",
        state="open",
    )


def question_for_missing(unit: SourceUnit, row: Mapping[str, Any]) -> OpenQuestion:
    """Ask about a transaction the assessor recorded nothing for.

    Args:
        unit: The transaction's unit.
        row: The transaction's row.

    Returns:
        An open question for a fraud analyst, of reason ``missing_data`` and high priority.
    """
    return OpenQuestion.build(
        about={"source_id": unit.source_id, "anchor": unit.anchor},
        question=f"No assessment was recorded for {_what(row)}. Should the payment be approved "
        "or blocked?",
        why_unknown="The assessor looked the transaction up and recorded no assessment of it, "
        "so there is no score, decision or reason to read.",
        impact="Until a person decides, the transaction is not on the brief.",
        ask_role=ASK_ROLE,
        reason="missing_data",
        cites=[unit.id],
        priority="high",
        state="open",
    )
