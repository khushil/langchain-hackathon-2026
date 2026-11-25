"""The ten measures of an engine's output for one application, as plain functions and for LangSmith.

An output is one application's result as ``evals.engine_outputs`` gives it: the proposed risk level
and decision, whether the checks settled it, the name and date of birth the reading gave, and how
many of the application's units were accounted for. The reference is an example's
``reference_outputs``, which carry the starter's label. Nothing here calls a model or imports the
engine; the starter's own rule is applied with the starter's own screening functions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fsi_common.evals.measures import Measure
from tools.screening import check_pep, check_sanctions

MEASURE_KEYS = (
    "risk_agrees",
    "decision_agrees",
    "settled_by_checks",
    "sent_to_person",
    "settled_agree",
    "edge_cases_sent",
    "starter_risk_agrees",
    "starter_decision_agrees",
    "applications_accounted",
    "screenings_accounted",
)
APPLICATIONS = "applications"
SETTLED = "applications settled by the checks"
EDGE = "applications the starter's labels mark as edge cases"
SCREENINGS = "screenings of an application against a list entry"


class MalformedOutputError(Exception):
    """An output or a reference does not have the shape the measures read."""


def starter_rule(name: str | None, date_of_birth: str | None) -> tuple[str, str]:
    """Apply the starter's own rule to a name and a date of birth.

    Any watchlist hit by the starter's name match makes the customer high risk, and the starter's
    evaluation has its stand-in reviewer reject every high-risk case and approve the rest.

    Args:
        name: The applicant's name; none is screened as an empty name, which hits nothing.
        date_of_birth: The date of birth, ``YYYY-MM-DD``, or None.

    Returns:
        The risk level and the decision.
    """
    hits = check_sanctions(name or "", date_of_birth or "") + check_pep(name or "")
    return ("high", "reject") if hits else ("low", "approve")


def _read(output: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]:
    missing = [
        k for k in ("risk_level", "decision", "settled", "profile", "accounting") if k not in output
    ]
    if missing:
        raise MalformedOutputError(f"the output lacks {', '.join(missing)}")
    wanted = [k for k in ("risk_level", "decision", "edge_case") if k not in reference]
    if wanted:
        raise MalformedOutputError(f"the reference lacks {', '.join(wanted)}")
    profile, accounting = output["profile"], output["accounting"]
    starter = starter_rule(profile.get("full_name"), profile.get("date_of_birth"))
    return {
        "agrees_risk": output["risk_level"] == reference["risk_level"],
        "agrees_decision": output["decision"] == reference["decision"],
        "settled": bool(output["settled"]),
        "edge": bool(reference["edge_case"]),
        "starter": starter,
        "reference": reference,
        "accounting": accounting,
    }


def _measure(key: str, population: str, hit: bool, *, in_scope: bool = True) -> Measure:
    return Measure(key, int(hit and in_scope), int(in_scope), population)


def _pair(key: str, population: str, counts: list[int]) -> Measure:
    accounted, units = counts
    return Measure(key, accounted, units, population)


def evaluate_pair(example: Mapping[str, Any], output: Mapping[str, Any]) -> list[Measure]:
    """Score one application's output on all ten measures.

    Args:
        example: A dataset example with ``reference_outputs``.
        output: The application's output from ``evals.engine_outputs``.

    Returns:
        The ten measures, in ``MEASURE_KEYS`` order, each over this one application.

    Raises:
        MalformedOutputError: If the output or the reference lacks a field a measure reads.
    """
    s = _read(output, example["reference_outputs"])
    ref = s["reference"]
    both = s["agrees_risk"] and s["agrees_decision"]
    starter_risk, starter_decision = s["starter"]
    return [
        _measure("risk_agrees", APPLICATIONS, s["agrees_risk"]),
        _measure("decision_agrees", APPLICATIONS, s["agrees_decision"]),
        _measure("settled_by_checks", APPLICATIONS, s["settled"]),
        _measure("sent_to_person", APPLICATIONS, not s["settled"]),
        _measure("settled_agree", SETTLED, both, in_scope=s["settled"]),
        _measure("edge_cases_sent", EDGE, not s["settled"], in_scope=s["edge"]),
        _measure("starter_risk_agrees", APPLICATIONS, starter_risk == ref["risk_level"]),
        _measure("starter_decision_agrees", APPLICATIONS, starter_decision == ref["decision"]),
        _pair("applications_accounted", APPLICATIONS, s["accounting"]["applications"]),
        _pair("screenings_accounted", SCREENINGS, s["accounting"]["screenings"]),
    ]


def _langsmith_evaluator(key: str) -> Callable[[dict, dict], dict]:
    def evaluate(outputs: dict, reference_outputs: dict) -> dict:
        scored = {
            m.key: m for m in evaluate_pair({"reference_outputs": reference_outputs}, outputs)
        }
        measure = scored[key]
        return {
            "key": key,
            "score": measure.score,
            "comment": measure.line().removeprefix(f"{key}: "),
        }

    evaluate.__name__ = key
    evaluate.__qualname__ = key
    evaluate.__doc__ = f"The {key} measure as a LangSmith evaluator."
    return evaluate


def langsmith_evaluators() -> list[Callable[[dict, dict], dict]]:
    """The ten measures as LangSmith evaluators, taking the outputs and the reference outputs.

    Returns:
        One function per measure, named after it. A measure with nothing in scope has no score
        and says so in its comment.
    """
    return [_langsmith_evaluator(key) for key in MEASURE_KEYS]
