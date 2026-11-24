"""Faults planted in a summary built from the labels, each of which the measures must catch."""

import copy
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .build_dataset import read_examples
from .evaluators import score_summary
from .reference_summary import document_summary, section_summary

Summary = dict[str, Any]
SECTION_FOR_SECTION_PLANTS = "7"


@dataclass(frozen=True)
class Plant:
    """One fault: how it changes a summary and the measures that must fall as a result."""

    name: str
    description: str
    level: str
    degrades: tuple[str, ...]
    apply: Callable[[Summary], Summary]


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


def _find(summary: Summary, paragraph: str, start: str) -> dict[str, Any]:
    pool = summary["sections"] if "sections" in summary else [summary]
    for section in pool:
        for obligation in section["obligations"]:
            if obligation["paragraph"] == paragraph and obligation["evidence"].startswith(start):
                return obligation
    raise LookupError(f"no obligation in {paragraph} opens with '{start}'")


def _section_with(summary: Summary, paragraph: str) -> Summary:
    pool = summary["sections"] if "sections" in summary else [summary]
    section_number = paragraph.split(".")[0]
    return next(s for s in pool if s["number"] == section_number)


def _paraphrase_quote(summary: Summary) -> Summary:
    obligation = _find(summary, "7.1", "Firms must submit an initial notification")
    obligation["evidence"] = obligation["evidence"].replace("must submit", "shall submit", 1)
    return summary


def _convert_deadline(summary: Summary) -> Summary:
    obligation = _find(summary, "7.1", "Firms must submit an initial notification")
    obligation["deadline"] = obligation["deadline"].replace(
        "within 4 hours", "within four hours", 1
    )
    return summary


def _invent_obligation(summary: Summary) -> Summary:
    summary["obligations"].append(
        {
            "requirement": "Publish an incident reporting template.",
            "paragraph": "7.5",
            "deadline": None,
            "evidence": (
                "We will publish an incident reporting template before the rules take effect."
            ),
        }
    )
    return summary


def _drop_obligation(summary: Summary) -> Summary:
    section = _section_with(summary, "7.3")
    target = _find(summary, "7.3", "The final report must include")
    section["obligations"].remove(target)
    return summary


def _drop_deadline(summary: Summary) -> Summary:
    _find(summary, "7.2", "Firms must submit an intermediate report")["deadline"] = None
    return summary


def _lose_paragraph(summary: Summary) -> Summary:
    section = _section_with(summary, "7.2")
    section["obligations"].remove(_find(summary, "7.2", "Firms must submit an intermediate report"))
    return summary


PLANTS: tuple[Plant, ...] = (
    Plant(
        "paraphrased_quote",
        "One word of the evidence for paragraph 7.1 is replaced",
        "section",
        ("quotes_word_for_word",),
        _paraphrase_quote,
    ),
    Plant(
        "converted_deadline",
        "'within 4 hours' for paragraph 7.1 is written 'within four hours'",
        "section",
        ("deadlines_as_written", "deadlines_matched"),
        _convert_deadline,
    ),
    Plant(
        "invented_obligation",
        "An obligation is added for paragraph 7.5",
        "section",
        ("invented_obligations", "paragraph_precision"),
        _invent_obligation,
    ),
    Plant(
        "dropped_obligation",
        "The second obligation of paragraph 7.3 is left out of the document",
        "document",
        ("obligations_found",),
        _drop_obligation,
    ),
    Plant(
        "dropped_deadline",
        "The deadline of the obligation in paragraph 7.2 is left out",
        "section",
        ("deadlines_matched",),
        _drop_deadline,
    ),
    Plant(
        "lost_paragraph",
        "The only obligation of paragraph 7.2 is left out",
        "section",
        ("obligations_found", "paragraph_recall"),
        _lose_paragraph,
    ),
)


def baseline_summary(example: dict[str, Any]) -> Summary:
    """The summary the plants start from: the labels themselves, as a section summary.

    Args:
        example: A line of `sections.jsonl`.

    Returns:
        The reference-built summary.
    """
    return section_summary(example)


def _degraded(before: list, after: list) -> list[str]:
    fell = []
    for old, new in zip(before, after, strict=True):
        if old.in_scope and (not new.in_scope or not new.is_full):
            fell.append(old.key)
    return sorted(fell)


def run_plants(plants: Sequence[Plant]) -> list[PlantResult]:
    """Plant each fault in a copy of the baseline and see which measures fall.

    Section plants start from the summary of section 7; document plants from all ten sections.

    Args:
        plants: The faults to try.

    Returns:
        One result per plant.
    """
    sections = read_examples("sections.jsonl")
    section = next(
        e for e in sections if e["inputs"]["section"]["number"] == SECTION_FOR_SECTION_PLANTS
    )
    document = read_examples("documents.jsonl")[0]
    results = []
    for plant in plants:
        if plant.level == "section":
            reference, base = section["reference_outputs"], baseline_summary(section)
        else:
            reference, base = document["reference_outputs"], document_summary(sections)
        before = score_summary(base, reference)
        after = score_summary(plant.apply(copy.deepcopy(base)), reference)
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
