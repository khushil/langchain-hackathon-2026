"""Faults planted in assessments built from the labels, each of which the measures must catch."""

import copy
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .build_dataset import read_examples
from .evaluators import score_assessments
from .reference_assessments import reference_assessments

Assessments = list[dict[str, Any]]


@dataclass(frozen=True)
class Plant:
    """One fault: how it changes the assessments and the measures that must fall as a result."""

    name: str
    description: str
    degrades: tuple[str, ...]
    apply: Callable[[Assessments], Assessments]


@dataclass(frozen=True)
class PlantResult:
    """Whether a plant was caught: the measures that fell, against the ones declared."""

    name: str
    degraded: list[str]
    expected: list[str]

    @property
    def caught(self) -> bool:
        """True when the measures that fell are exactly the declared ones."""
        return bool(self.expected) and self.degraded == self.expected

    def line(self) -> str:
        """One line for the report, CAUGHT or MISSED, with the measures that fell."""
        if self.caught:
            return f"CAUGHT {self.name}: {', '.join(self.degraded)} fell"
        fell = ", ".join(self.degraded) or "nothing"
        return f"MISSED {self.name}: expected {', '.join(self.expected)} to fall, but {fell} fell"


def _find(assessments: Assessments, tx: str) -> dict[str, Any]:
    return next(a for a in assessments if a["transaction_id"] == tx)


def _approved_a_block(assessments: Assessments) -> Assessments:
    _find(assessments, "TX-2004")["decision"] = "approve"
    return assessments


def _blocked_an_approval(assessments: Assessments) -> Assessments:
    _find(assessments, "TX-1001")["decision"] = "block"
    return assessments


def _score_far_off(assessments: Assessments) -> Assessments:
    _find(assessments, "TX-1006")["risk_score"] = 72
    return assessments


def _ambiguous_not_flagged(assessments: Assessments) -> Assessments:
    _find(assessments, "TX-1003")["confidence"] = 0.9
    return assessments


def _clear_flagged(assessments: Assessments) -> Assessments:
    _find(assessments, "TX-1001")["confidence"] = 0.5
    return assessments


def _dropped_assessment(assessments: Assessments) -> Assessments:
    return [a for a in assessments if a["transaction_id"] != "TX-2003"]


PLANTS: tuple[Plant, ...] = (
    Plant(
        "approved_a_block",
        "The Singapore jewellery, which analysts block at 95, is proposed as an approval",
        ("blocks_found", "decisions_agree"),
        _approved_a_block,
    ),
    Plant(
        "blocked_an_approval",
        "A small grocery shop is proposed as a block",
        ("decisions_agree", "false_blocks"),
        _blocked_an_approval,
    ),
    Plant(
        "score_far_off",
        "The gift cards, which analysts score at 95, are scored at 72, still a block",
        ("scores_in_band",),
        _score_far_off,
    ),
    Plant(
        "ambiguous_not_flagged",
        "The hotel in Lisbon, which analysts call ambiguous, is recorded with a high confidence",
        ("ambiguous_flagged",),
        _ambiguous_not_flagged,
    ),
    Plant(
        "clear_flagged",
        "A small grocery shop is recorded with a confidence that would ask a person",
        ("clear_not_flagged",),
        _clear_flagged,
    ),
    Plant(
        "dropped_assessment",
        "The coffee in Lisbon is never assessed",
        ("assessed", "clear_not_flagged", "decisions_agree", "scores_in_band"),
        _dropped_assessment,
    ),
)


def labelled_example() -> dict[str, Any]:
    """Return the eleven analyst-labelled transactions as one example.

    Returns:
        An example whose labels are those of the two streams before 19 October.
    """
    labels: dict[str, Any] = {}
    for example in read_examples()[:2]:
        labels |= example["reference_outputs"]["labels"]
    return {"key": "labelled", "reference_outputs": {"labels": labels}}


def baseline(example: dict[str, Any]) -> Assessments:
    """The assessments the plants start from: the labels themselves.

    Args:
        example: A dataset example.

    Returns:
        The reference-built assessments, which score in full.
    """
    return reference_assessments(example)


def _degraded(before: list, after: list) -> list[str]:
    fell = []
    for old, new in zip(before, after, strict=True):
        if old.in_scope and (not new.in_scope or not new.is_full):
            fell.append(old.key)
    return sorted(fell)


def run_plants(plants: Sequence[Plant]) -> list[PlantResult]:
    """Plant each fault in a copy of the baseline and see which measures fall.

    Args:
        plants: The faults to try.

    Returns:
        One result per plant.
    """
    example = labelled_example()
    reference = example["reference_outputs"]
    base = baseline(example)
    before = score_assessments(base, reference)
    results = []
    for plant in plants:
        after = score_assessments(plant.apply(copy.deepcopy(base)), reference)
        results.append(PlantResult(plant.name, _degraded(before, after), sorted(plant.degrades)))
    return results


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
