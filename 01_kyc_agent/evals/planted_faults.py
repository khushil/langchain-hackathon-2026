"""Faults planted in outputs built from the labels, each of which the measures must catch."""

from __future__ import annotations

import copy
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fsi_common.evals.runner import run_evaluators

from .build_dataset import read_examples
from .evaluators import MEASURE_KEYS, evaluate_pair
from .labels import read_labels

PROFILES_PATH = Path(__file__).resolve().parent / "data" / "baseline_profiles.tsv"
UNITS = 14
Outputs = dict[str, dict[str, Any]]


@dataclass(frozen=True)
class Plant:
    """One fault: how it changes the outputs and the measures that must move as a result."""

    name: str
    description: str
    moves: tuple[str, ...]
    apply: Callable[[Outputs], Outputs]


@dataclass(frozen=True)
class PlantResult:
    """Whether a plant was caught: the measures that moved, against the ones declared."""

    name: str
    moved: list[str]
    expected: list[str]

    @property
    def caught(self) -> bool:
        """True when the measures that moved are the declared ones and no others."""
        return bool(self.expected) and self.moved == self.expected

    def line(self) -> str:
        """One line for the report, CAUGHT or MISSED, with the measures that moved."""
        if self.caught:
            return f"CAUGHT {self.name}: {', '.join(self.moved)} moved"
        shown = ", ".join(self.moved) or "nothing"
        return f"MISSED {self.name}: expected {', '.join(self.expected)} to move, but {shown} moved"


def read_profiles() -> dict[str, dict[str, str]]:
    """Read the name and date of birth each application states.

    Returns:
        For each customer id, its full name and its date of birth.
    """
    rows = [
        line.split("\t")
        for line in PROFILES_PATH.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ][1:]
    return {r[0]: {"full_name": r[1], "date_of_birth": r[2]} for r in rows}


def baseline_outputs() -> Outputs:
    """The outputs the plants start from: each application as the starter's label has it.

    Every application agrees with its label, the labelled edge cases are held for a person and the
    rest are settled by the checks, and every unit is accounted for.

    Returns:
        One output for each application, in the shape ``evals.evaluators`` reads.
    """
    profiles = read_profiles()
    return {
        label.customer_id: {
            "customer_id": label.customer_id,
            "risk_level": label.risk_level,
            "decision": label.decision,
            "settled": not label.edge_case,
            "profile": dict(profiles[label.customer_id]),
            "accounting": {"applications": [1, 1], "screenings": [UNITS, UNITS]},
        }
        for label in read_labels()
    }


def totals_of(outputs: Outputs) -> dict[str, tuple[int, int]]:
    """Score outputs on every measure and total each over the applications.

    Args:
        outputs: One output for each application.

    Returns:
        Each measure's key with its numerator and denominator.
    """
    pairs = [(example, outputs[example["key"]]) for example in read_examples()]
    report = run_evaluators(pairs, [evaluate_pair])
    return {m.key: (m.numerator, m.denominator) for m in report.totals}


def _wrong_risk(outputs: Outputs) -> Outputs:
    outputs["CUST-018"]["risk_level"] = "high"
    return outputs


def _wrong_decision(outputs: Outputs) -> Outputs:
    outputs["CUST-021"]["decision"] = "reject"
    return outputs


def _wrong_settled(outputs: Outputs) -> Outputs:
    outputs["CUST-001"]["risk_level"] = "high"
    return outputs


def _edge_settled(outputs: Outputs) -> Outputs:
    outputs["CUST-015"]["settled"] = True
    return outputs


def _blind_starter(outputs: Outputs) -> Outputs:
    outputs["CUST-002"]["profile"] = {"full_name": None, "date_of_birth": None}
    return outputs


def _drop_screening(outputs: Outputs) -> Outputs:
    outputs["CUST-004"]["accounting"]["screenings"] = [UNITS - 1, UNITS]
    return outputs


def _drop_application(outputs: Outputs) -> Outputs:
    outputs["CUST-004"]["accounting"]["applications"] = [0, 1]
    return outputs


PLANTS: tuple[Plant, ...] = (
    Plant(
        "wrong_risk_on_a_held_application",
        "The risk level proposed for an application held for a person is the wrong one",
        ("risk_agrees",),
        _wrong_risk,
    ),
    Plant(
        "wrong_decision_on_a_held_application",
        "The decision proposed for an application held for a person is the wrong one",
        ("decision_agrees",),
        _wrong_decision,
    ),
    Plant(
        "wrong_settled_proposal",
        "An application the checks settled is given the wrong risk level",
        ("risk_agrees", "settled_agree"),
        _wrong_settled,
    ),
    Plant(
        "edge_case_settled_by_the_checks",
        "An application the labels mark as an edge case is settled by the checks, not sent",
        ("edge_cases_sent", "sent_to_person", "settled_agree", "settled_by_checks"),
        _edge_settled,
    ),
    Plant(
        "starter_rule_blinded",
        "The reading gives no name for an application the starter's rule would catch",
        ("starter_decision_agrees", "starter_risk_agrees"),
        _blind_starter,
    ),
    Plant(
        "screening_dropped",
        "One screening of one application is not accounted for",
        ("screenings_accounted",),
        _drop_screening,
    ),
    Plant(
        "application_dropped",
        "One application is not accounted for",
        ("applications_accounted",),
        _drop_application,
    ),
)


def _moved(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    return sorted(key for key in MEASURE_KEYS if before[key] != after[key])


def run_plants(plants: Sequence[Plant]) -> list[PlantResult]:
    """Plant each fault in a copy of the baseline and see which measures move.

    Args:
        plants: The faults to try.

    Returns:
        One result for each plant.
    """
    base = baseline_outputs()
    before = totals_of(base)
    return [
        PlantResult(
            plant.name,
            _moved(before, totals_of(plant.apply(copy.deepcopy(base)))),
            sorted(plant.moves),
        )
        for plant in plants
    ]


def main() -> int:
    """Run every plant, print one line each, and exit non-zero if any is missed.

    Returns:
        0 when every plant is caught, otherwise 1.
    """
    results = run_plants(PLANTS)
    for result in results:
        print(result.line())
    caught = sum(r.caught for r in results)
    print(f"{caught} of {len(results)} plants caught")
    return 0 if caught == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
