"""The sentences that say what a floor of 0.65 would lose are held to the screening run."""

import re

from engine_fakes import Harness

from context import screening
from utils import PROJECT_ROOT

README = (PROJECT_ROOT.parent / "README.md").read_text(encoding="utf-8")
DOCSTRING = screening.__doc__
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "nine": 9}
CLAIM = re.compile(
    r"(?:raising it|a floor) (?:to|of) 0\.65 would\s+(?:stop|lose)\s+(?:the\s+)?(\w+)\s+pairs?"
)


def pairs_a_higher_floor_would_lose() -> int:
    """Count the screening facts a run keeps whose score is from the floor up to 0.65."""
    harness = Harness()
    values = harness.values(harness.start())
    kept = [c[0] for c in values["facts"].values() if c[0]["kind"] == "screening"]
    return sum(
        screening.NEAR_FLOOR <= float(fact["attributes"]["name_score"]) < 0.65 for fact in kept
    )


def problems(text: str, count: int) -> list[str]:
    """Name each sentence of a text about a floor of 0.65 that is not the count."""
    found = []
    claims = CLAIM.findall(text)
    if not claims:
        found.append("no sentence says what a floor of 0.65 would lose")
    for word in claims:
        if WORDS.get(word) != count:
            found.append(f"says {word}, the run has {count}")
    return found


def test_the_run_keeps_three_pairs_between_the_floor_and_0_65():
    assert pairs_a_higher_floor_would_lose() == 3


def test_the_readme_says_how_many_pairs_a_floor_of_0_65_would_lose():
    assert problems(README, pairs_a_higher_floor_would_lose()) == []


def test_the_docstring_says_how_many_pairs_a_floor_of_0_65_would_lose():
    assert problems(DOCSTRING, pairs_a_higher_floor_would_lose()) == []


def test_a_wrong_count_in_either_sentence_is_named():
    count = pairs_a_higher_floor_would_lose()
    planted = README.replace("stop the three pairs", "stop the nine pairs")
    assert problems(planted, count) == [f"says nine, the run has {count}"]
    assert problems("a floor of 0.65 would lose the 0.640 pair", count) == [
        "no sentence says what a floor of 0.65 would lose"
    ]
