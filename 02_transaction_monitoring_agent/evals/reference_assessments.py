"""Assessments built from the analysts' labels, which score in full on every measure."""

from collections.abc import Mapping
from typing import Any

CLEAR_CONFIDENCE = 0.9
AMBIGUOUS_CONFIDENCE = 0.5
"""What the starter's tool records for a clear case and for a grey-zone case: the model's own
confidence, and the confidence the starter's checks lower a grey-zone case to."""


def reference_assessments(example: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build the assessments an assessor that agreed with the analysts would record.

    Args:
        example: A dataset example with ``reference_outputs``.

    Returns:
        One assessment for each labelled transaction: the analyst's score and decision, a
        confidence below the starter's threshold where the analysts called it ambiguous and above
        it elsewhere.
    """
    return [
        {
            "transaction_id": tx,
            "risk_score": label["risk_score"],
            "decision": label["decision"],
            "confidence": AMBIGUOUS_CONFIDENCE if label["ambiguous"] else CLEAR_CONFIDENCE,
        }
        for tx, label in example["reference_outputs"]["labels"].items()
    ]
