"""The repository README's figures for this topic are the lines the first notebook printed."""

from __future__ import annotations

import re

from notebook_support import NAMES, STARTER_CELLS, TOPIC, load, text_of

README = (TOPIC.parent / "README.md").read_text(encoding="utf-8")
SECTION = "## Transaction monitoring"
COLUMNS = ("starter's agent", "this workflow", "this workflow, week after")
MEASURES = {
    "Transactions with an assessment": "assessed",
    "Decision agrees with the analysts'": "decisions_agree",
    "Blocks found": "blocks_found",
    "Approvals blocked (lower is better)": "false_blocks",
    "Scores within 20 points of the analysts'": "scores_in_band",
    "Ambiguous transactions flagged for a person": "ambiguous_flagged",
    "Clear transactions not flagged": "clear_not_flagged",
}
ACCOUNTING = {
    "15 of 15 transactions of the starter's data accounted for across 2 runs": (
        "all 15 transactions are accounted for across the 2 runs"
    ),
    "Assessments that passed every plain-code check: 15 of 15": (
        "15 of 15 assessments passed every plain-code check"
    ),
}


def printed() -> str:
    """Return what the code cells after the starter's in notebook 1 printed."""
    cells = load(NAMES[0]).cells[STARTER_CELLS[NAMES[0]] :]
    return "\n".join(text_of(c) for c in cells if c.cell_type == "code")


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    rest = text[start + len(heading) :]
    end = re.search(r"^## ", rest, re.M)
    return rest[: end.start()] if end else rest


def notebook_rows() -> dict[str, list[str]]:
    """Read the side-by-side scoring cell: a measure, then one indented line for each column."""
    rows: dict[str, list[str]] = {}
    measure = None
    for line in printed().splitlines():
        if line in MEASURES.values():
            measure = line
            rows[measure] = []
        elif measure and line.startswith("    "):
            label, _, figure = line.strip().partition("  ")
            assert label in COLUMNS, line
            rows[measure].append(figure.strip())
    return rows


def readme_rows(text: str = README) -> dict[str, list[str]]:
    rows = {}
    for line in section(text, SECTION).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] in MEASURES:
            rows[MEASURES[cells[0]]] = cells[1:]
    return rows


def mismatches(text: str = README) -> list[str]:
    """Name each measure whose row in the README is not the figures the notebook printed."""
    printed_rows, written = notebook_rows(), readme_rows(text)
    found = [f"{k} is missing" for k in MEASURES.values() if k not in written]
    found += [f"{k} is not printed" for k in MEASURES.values() if k not in printed_rows]
    for key, figures in printed_rows.items():
        if key in written and written[key] != figures:
            found.append(key)
    for line, words in ACCOUNTING.items():
        if line not in printed() or words not in text:
            found.append(line)
    return found


def test_the_readme_has_a_section_for_this_topic():
    assert SECTION in README


def test_each_figure_of_the_readme_table_is_the_line_the_notebook_printed():
    assert mismatches() == []


def test_the_notebook_prints_a_row_of_three_figures_for_each_measure():
    rows = notebook_rows()
    assert sorted(rows) == sorted(MEASURES.values())
    assert all(len(figures) == 3 for figures in rows.values())


def test_a_figure_changed_in_the_readme_is_found():
    row = next(
        line
        for line in README.splitlines()
        if line.startswith("| Decision agrees with the analysts'")
    )
    changed = README.replace(row, row.replace("11 of 11", "10 of 11", 1), 1)
    assert changed != README
    assert mismatches(changed) == ["decisions_agree"]
    assert "blocks_found is missing" in mismatches(README.replace("| Blocks found |", "| Blocks |"))
    assert mismatches(README.replace("15 of 15 assessments passed", "14 of 15 assessments passed"))


def notebook_two_printed() -> str:
    """Return what the second notebook's scoring cell printed for its two experiments."""
    cells = load(NAMES[1]).cells[STARTER_CELLS[NAMES[1]] :]
    return "\n".join(text_of(c) for c in cells if c.cell_type == "code")


def experiment_blocks() -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    name = None
    for line in notebook_two_printed().splitlines():
        if line and not line.startswith(" ") and ":" not in line:
            name = line
            blocks[name] = []
        elif name and line.startswith("    "):
            blocks[name].append(line.strip())
    return blocks


def test_the_readmes_week_after_sentence_is_the_notebooks_line_and_the_starters_threshold():
    from utils import db
    from utils.state import MyAgentContext

    claim = re.search(
        r"TX-1009, [^,]*?score of (\d+)[^,]*, was assessed as a block at a confidence of "
        r"([\d.]+), below the ([\d.]+) at which",
        section(README, SECTION),
    )
    assert claim, "the README no longer says what became of TX-1009"
    reviewer, confidence, threshold = claim.groups()
    assert reviewer == str(
        db.get("simulated_annotations", transaction_id="TX-1009")["correct_risk_score"]
    )
    assert threshold == str(MyAgentContext().confidence_threshold)
    line = re.search(r"tx:TX-1009 +proposed block +score +(\d+) +confidence ([\d.]+)", printed())
    assert line, "the notebook printed no line for TX-1009"
    assert (line.group(1), line.group(2)) == (reviewer, confidence)
    assert float(confidence) < float(threshold)


def test_the_two_experiments_score_the_same_when_the_readme_says_they_do():
    blocks = experiment_blocks()
    assert sorted(blocks) == ["baseline", "threshold-0.8"]
    says_same = "score the same on the 11 labelled transactions" in section(README, SECTION)
    assert says_same == (blocks["baseline"] == blocks["threshold-0.8"])
    assert says_same, "the README no longer says the two experiments score the same"
