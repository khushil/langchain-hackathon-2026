"""The seven measures of a customer's assessments, as plain functions and as LangSmith evaluators.

An assessment is a transaction id, the risk score the assessor gave, the decision it proposed and
its confidence: ``{"transaction_id", "risk_score", "decision", "confidence"}``. The reference is an
example's ``reference_outputs``, the analysts' label for each transaction. Nothing here calls a
model or imports the system it scores; the thresholds are the starter's own, written out.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from fsi_common.evals.measures import Measure

MEASURE_KEYS = (
    "assessed",
    "decisions_agree",
    "blocks_found",
    "false_blocks",
    "scores_in_band",
    "ambiguous_flagged",
    "clear_not_flagged",
)
BAND = 20
"""How far a score may lie from the analyst's and still count as in band: the starter's own
judge treats a reviewer within 20 points as agreeing."""
FLAG_BELOW = 0.7
"""The starter's confidence threshold: below it the starter's agent asks a person."""
LABELLED = "labelled transactions"


class MalformedAssessmentError(Exception):
    """An assessment or a reference does not have the shape the measures read."""


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _read(assessments: Sequence[Any]) -> dict[str, Mapping[str, Any]]:
    held: dict[str, Mapping[str, Any]] = {}
    for item in assessments:
        if not isinstance(item, Mapping) or not {
            "transaction_id",
            "risk_score",
            "decision",
            "confidence",
        } <= set(item):
            raise MalformedAssessmentError(
                "an assessment needs a transaction_id, risk_score, decision and confidence"
            )
        held[str(item["transaction_id"])] = item
    return held


def _labels(reference: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    labels = reference.get("labels")
    if not isinstance(labels, Mapping):
        raise MalformedAssessmentError("the reference needs labels")
    return dict(labels)


def _flagged(item: Mapping[str, Any]) -> bool:
    confidence = item["confidence"]
    return _number(confidence) and confidence < FLAG_BELOW


def score_assessments(assessments: Sequence[Any], reference: Mapping[str, Any]) -> list[Measure]:
    """Score a list of assessments on all seven measures.

    A transaction with no assessment misses every measure it is in the population of, except
    ``false_blocks``, where an assessment that does not exist is not a block.

    Args:
        assessments: The assessments, one for each transaction the assessor looked at.
        reference: An example's ``reference_outputs``.

    Returns:
        The seven measures, in ``MEASURE_KEYS`` order.

    Raises:
        MalformedAssessmentError: If an assessment or the reference has the wrong shape.
    """
    held, labels = _read(assessments), _labels(reference)
    done = [t for t in labels if t in held]
    agree = [t for t in done if held[t]["decision"] == labels[t]["decision"]]
    blocks = [t for t, label in labels.items() if label["decision"] == "block"]
    approvals = [t for t, label in labels.items() if label["decision"] == "approve"]
    in_band = [
        t
        for t in done
        if _whole(held[t]["risk_score"])
        and abs(held[t]["risk_score"] - labels[t]["risk_score"]) <= BAND
    ]
    ambiguous = [t for t, label in labels.items() if label["ambiguous"]]
    clear = [t for t, label in labels.items() if not label["ambiguous"]]
    return [
        Measure("assessed", len(done), len(labels), LABELLED),
        Measure("decisions_agree", len(agree), len(labels), LABELLED),
        Measure(
            "blocks_found",
            sum(t in held and held[t]["decision"] == "block" for t in blocks),
            len(blocks),
            "labelled blocks",
        ),
        Measure(
            "false_blocks",
            sum(t in held and held[t]["decision"] == "block" for t in approvals),
            len(approvals),
            "labelled approvals",
            lower_is_better=True,
        ),
        Measure("scores_in_band", len(in_band), len(labels), LABELLED),
        Measure(
            "ambiguous_flagged",
            sum(t in held and _flagged(held[t]) for t in ambiguous),
            len(ambiguous),
            "labelled ambiguous transactions",
        ),
        Measure(
            "clear_not_flagged",
            sum(t in held and not _flagged(held[t]) for t in clear),
            len(clear),
            "labelled clear transactions",
        ),
    ]


def evaluate_pair(example: Mapping[str, Any], output: Sequence[Any]) -> list[Measure]:
    """Score an output against an example, in the shape the runner expects.

    Args:
        example: A dataset example with ``reference_outputs``.
        output: The assessments to score.

    Returns:
        The seven measures.

    Raises:
        MalformedAssessmentError: If the output or the example has the wrong shape.
    """
    return score_assessments(output, example["reference_outputs"])


def assessments_from_log(log: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Read the starter's decision log as assessments.

    Args:
        log: What the starter's ``decision_log`` returns: the audit record of each decision.

    Returns:
        The assessments, taking the agent's own decision, not the final one, because a person
        decides the final one.
    """
    return [
        {
            "transaction_id": d["transaction_id"],
            "risk_score": d["risk_score"],
            "decision": d["agent_decision"],
            "confidence": d["confidence"],
        }
        for d in log
    ]


def assessments_from_raw(raw: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Read a run's raw records as assessments, leaving out a transaction with no record.

    Args:
        raw: For each transaction, what the assessor recorded (``audit``) and said (``reply``).

    Returns:
        The assessments, in the order the run holds them.
    """
    return [
        {
            "transaction_id": tx,
            "risk_score": record["audit"]["risk_score"],
            "decision": record["audit"]["agent_decision"],
            "confidence": record["audit"]["confidence"],
        }
        for tx, record in raw.items()
        if record.get("audit") is not None
    ]


def _langsmith_evaluator(key: str) -> Callable[[dict, dict], dict]:
    def evaluate(outputs: dict, reference_outputs: dict) -> dict:
        scored = {m.key: m for m in score_assessments(outputs["assessments"], reference_outputs)}[
            key
        ]
        comment = scored.line().removeprefix(f"{key}: ")
        return {"key": key, "score": scored.score, "comment": comment}

    evaluate.__name__ = key
    evaluate.__qualname__ = key
    evaluate.__doc__ = f"The {key} measure as a LangSmith evaluator."
    return evaluate


def langsmith_evaluators() -> list[Callable[[dict, dict], dict]]:
    """The seven measures as LangSmith evaluators, taking the outputs and the reference outputs.

    Returns:
        One function per measure, named after it; the outputs hold ``assessments``. A measure
        with nothing in scope has no score and says so in its comment.
    """
    return [_langsmith_evaluator(key) for key in MEASURE_KEYS]
