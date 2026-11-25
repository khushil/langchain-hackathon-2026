"""The reviewer's wording for the seed: each decision on a proposal and each answer to a question.

Every sentence is the fictional reviewer's, in ``seed_wording.json``, and goes into the application
only through its review routes. The seed refits to a new recorded run by editing that file:
``decisions`` has one entry for each application's proposal, whether the checks settled it or left
it to a person, and ``questions`` has one entry for each open question, found by the
application and the place it is about (``sanctions-5``, ``pep-1`` or ``relation``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

WORDING = Path(__file__).with_name("seed_wording.json")


@dataclass(frozen=True)
class SeedDecision:
    """One decision of the fictional reviewer on one application's proposal."""

    customer: str
    outcome: str
    reason: str
    amendment: str | None = None


@dataclass(frozen=True)
class SeedQuestion:
    """The reviewer's handling of one open question: an answer, or an assumption in her words."""

    customer: str
    place: str
    answer: str | None = None
    reason: str | None = None
    assumption: str | None = None


def _load() -> tuple[tuple[SeedDecision, ...], tuple[SeedQuestion, ...]]:
    held = json.loads(WORDING.read_text(encoding="utf-8"))
    return (
        tuple(SeedDecision(**d) for d in held["decisions"]),
        tuple(SeedQuestion(**q) for q in held["questions"]),
    )


DECISIONS, QUESTIONS = _load()
