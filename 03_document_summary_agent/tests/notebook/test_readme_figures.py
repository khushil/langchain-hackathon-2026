"""The README's measure table and the sentences that quote it match what the notebook printed.

The committed notebook holds the output of its two scoring cells: the starter's agent over all
ten sections, and the starter's agent beside this engine on section 7. The README quotes both, so
a new recording that changes a figure cannot leave the README stale: this test names each figure
that differs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

TOPIC = Path(__file__).resolve().parents[2]
REPO = TOPIC.parent
NOTEBOOK = TOPIC / "modules" / "01_document_summary_agent.ipynb"
README = REPO / "README.md"

MEASURES = {
    "Obligations found": "obligations_found",
    "Invented obligations": "invented_obligations",
    "Quotes word for word": "quotes_word_for_word",
    "Deadlines as written": "deadlines_as_written",
    "Deadlines matched": "deadlines_matched",
    "Paragraph recall": "paragraph_recall",
    "Paragraph precision": "paragraph_precision",
}
COLUMNS = ("all ten sections", "starter's agent on section 7", "this engine on section 7")
FIGURE = re.compile(r"(\d+) of (\d+)")


class FiguresNotFoundError(Exception):
    """The notebook or the README lacks the output or the table the comparison reads."""


def cell_outputs(notebook: dict) -> list[str]:
    """Return each code cell's printed text."""
    out = []
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        text = "".join("".join(o.get("text", [])) for o in cell.get("outputs", []))
        out.append(text)
    return out


def printed_figures(notebook: dict) -> dict[str, dict[str, str]]:
    """Read the figures the two scoring cells printed.

    Args:
        notebook: The notebook as JSON.

    Returns:
        For each measure key, its figure in each of the three columns, as "N of M".

    Raises:
        FiguresNotFoundError: If a scoring cell's output is missing or is not found once.
    """
    whole = [t for t in cell_outputs(notebook) if "sections returned a summary" in t]
    section = [
        t for t in cell_outputs(notebook) if re.search(r"^obligations_found\n\s+starter", t, re.M)
    ]
    if len(whole) != 1 or len(section) != 1:
        raise FiguresNotFoundError(
            f"The notebook holds {len(whole)} whole-document and {len(section)} section 7 scoring "
            "outputs; each must be there once."
        )
    figures: dict[str, dict[str, str]] = {}
    for key in MEASURES.values():
        line = re.search(rf"^{key}: (\d+ of \d+)", whole[0], re.M)
        starter = re.search(rf"^{key}\n\s+starter's agent\s+(\d+ of \d+)", section[0], re.M)
        ours = re.search(
            rf"^{key}\n\s+starter's agent.*\n\s+this repository's engine\s+(\d+ of \d+)",
            section[0],
            re.M,
        )
        if not (line and starter and ours):
            raise FiguresNotFoundError(f"The notebook's scoring output does not print {key}.")
        figures[key] = dict(zip(COLUMNS, (line[1], starter[1], ours[1]), strict=True))
    return figures


def readme_table(readme: str) -> dict[str, dict[str, str]]:
    """Read the README's measure table.

    Args:
        readme: The README's text.

    Returns:
        For each measure key, its figure in each of the three columns.

    Raises:
        FiguresNotFoundError: If a measure has no row or a row has no three figures.
    """
    rows = [line for line in readme.splitlines() if line.startswith("|")]
    found: dict[str, dict[str, str]] = {}
    for label, key in MEASURES.items():
        matches = [r for r in rows if r.split("|")[1].strip().startswith(label)]
        if len(matches) != 1:
            raise FiguresNotFoundError(
                f"The README's measure table has {len(matches)} rows for '{label}'; it needs one."
            )
        cells = [c.strip() for c in matches[0].strip().strip("|").split("|")[1:]]
        if len(cells) != 3 or not all(FIGURE.fullmatch(c) for c in cells):
            raise FiguresNotFoundError(f"The row for '{label}' does not hold three figures.")
        found[key] = dict(zip(COLUMNS, cells, strict=True))
    return found


def readme_sentences(readme: str) -> dict[str, tuple[int, int]]:
    """Read the two figures the README's text repeats from the table."""
    missed = re.search(r"missed (\d+) of (\d+) labelled obligations", readme)
    invented = re.search(r"(\d+) of the (\d+) obligations it returned match no label", readme)
    if not (missed and invented):
        raise FiguresNotFoundError(
            "The README no longer says how many labelled obligations the starter's agent missed "
            "and how many of its obligations match no label."
        )
    return {
        "missed": (int(missed[1]), int(missed[2])),
        "invented": (int(invented[1]), int(invented[2])),
    }


def figure_problems(readme: str, notebook: dict) -> list[str]:
    """Name every README figure that differs from the notebook's printed output.

    Args:
        readme: The README's text.
        notebook: The notebook as JSON.

    Returns:
        One sentence for each figure that differs; empty when the README is current.
    """
    printed, table = printed_figures(notebook), readme_table(readme)
    problems = []
    for label, key in MEASURES.items():
        for column in COLUMNS:
            if table[key][column] != printed[key][column]:
                problems.append(
                    f"README: '{label}', {column}, says {table[key][column]}; "
                    f"the notebook printed {printed[key][column]}."
                )
    found, total = map(int, printed["obligations_found"]["all ten sections"].split(" of "))
    wrong, predicted = map(int, printed["invented_obligations"]["all ten sections"].split(" of "))
    said = readme_sentences(readme)
    if said["missed"] != (total - found, total):
        problems.append(
            f"README: the text says {said['missed'][0]} of {said['missed'][1]} labelled "
            f"obligations were missed; the notebook printed {total - found} of {total}."
        )
    if said["invented"] != (wrong, predicted):
        problems.append(
            f"README: the text says {said['invented'][0]} of the {said['invented'][1]} obligations "
            f"match no label; the notebook printed {wrong} of {predicted}."
        )
    return problems


@pytest.fixture(scope="module")
def notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


def test_the_readmes_measure_table_and_sentences_match_what_the_notebook_printed(readme, notebook):
    assert figure_problems(readme, notebook) == []


def test_the_notebook_prints_all_seven_measures_in_all_three_columns(notebook):
    printed = printed_figures(notebook)
    assert set(printed) == set(MEASURES.values())
    assert all(set(v) == set(COLUMNS) for v in printed.values())


def test_a_planted_figure_in_the_table_is_named(readme, notebook):
    changed = readme.replace("| 28 of 28 |", "| 26 of 26 |", 1)
    assert changed != readme
    problems = figure_problems(changed, notebook)
    assert problems == [
        "README: 'Deadlines as written', all ten sections, says 26 of 26; "
        "the notebook printed 28 of 28."
    ]


def test_a_planted_figure_in_each_column_is_named_in_its_column(readme, notebook):
    for column, old, new in (
        (COLUMNS[1], "| 5 of 5 | 4 of 4 |", "| 4 of 4 | 4 of 4 |"),
        (COLUMNS[2], "| 5 of 5 | 4 of 4 |", "| 5 of 5 | 5 of 5 |"),
    ):
        changed = readme.replace(old, new, 1)
        assert changed != readme
        problems = figure_problems(changed, notebook)
        assert len(problems) == 1 and column in problems[0], problems


def test_a_planted_figure_in_the_text_is_named(readme, notebook):
    changed = re.sub(r"missed \d+ of 39", "missed 2 of 39", readme)
    assert any(
        "says 2 of 39 labelled obligations were missed" in p
        for p in figure_problems(changed, notebook)
    )
    changed = re.sub(r"\d+ of the 45 obligations", "6 of the 45 obligations", readme)
    assert any(
        "says 6 of the 45 obligations match no label" in p
        for p in figure_problems(changed, notebook)
    )


def test_a_readme_with_a_measure_row_removed_fails_in_words(readme, notebook):
    kept = "\n".join(
        line for line in readme.splitlines() if not line.startswith("| Paragraph recall")
    )
    with pytest.raises(FiguresNotFoundError, match="0 rows for 'Paragraph recall'"):
        figure_problems(kept, notebook)


def test_a_notebook_without_the_scoring_output_fails_in_words(readme, notebook):
    stripped = {
        **notebook,
        "cells": [
            {**c, "outputs": []} if c["cell_type"] == "code" else c for c in notebook["cells"]
        ],
    }
    with pytest.raises(FiguresNotFoundError, match="each must be there once"):
        figure_problems(readme, stripped)
