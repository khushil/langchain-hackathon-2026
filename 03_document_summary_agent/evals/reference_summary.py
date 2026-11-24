"""Section summaries built from the reference labels, and a check that they score in full."""

import sys
from collections.abc import Mapping, Sequence
from typing import Any

from fsi_common.evals.runner import run_evaluators

from .evaluators import MEASURE_KEYS, evaluate_pair


def section_summary(example: Mapping[str, Any]) -> dict[str, Any]:
    """Build the summary a perfect sub-agent would return for a section example.

    Args:
        example: A line of `sections.jsonl`.

    Returns:
        A section summary as JSON: one obligation per labelled obligation, with its deadline
        and evidence as labelled.
    """
    section = example["inputs"]["section"]
    obligations = [
        {
            "requirement": item["requirement"],
            "paragraph": item["paragraph"],
            "deadline": item["deadline_as_written"],
            "evidence": item["evidence"],
        }
        for item in example["reference_outputs"]["items"]
        if item["kind"] == "obligation"
    ]
    return {
        "number": section["number"],
        "title": section["title"],
        "summary": f"Section {section['number']}, {section['title']}.",
        "obligations": obligations,
    }


def document_summary(sections: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build the document-level output from the section examples.

    Args:
        sections: The lines of `sections.jsonl`.

    Returns:
        An object whose `sections` are the reference-built summaries.
    """
    return {"sections": [section_summary(example) for example in sections]}


def main() -> int:
    """Score the reference-built summaries of all sections and require every measure in full.

    Returns:
        0 when every measure with something in scope is at its best, otherwise 1.
    """
    from .build_dataset import read_examples

    examples = read_examples("sections.jsonl")
    pairs = [(example, section_summary(example)) for example in examples]
    report = run_evaluators(pairs, [evaluate_pair], required=MEASURE_KEYS)
    print(report.render())
    short = [m.line() for m in report.totals if not m.is_full]
    for line in short:
        print(f"FAIL not full: {line}")
    return 1 if short else report.exit_code


if __name__ == "__main__":
    sys.exit(main())
