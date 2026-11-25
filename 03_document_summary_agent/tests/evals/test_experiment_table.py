"""The README's spread table matches the experiments file, cell by cell.

Until the experiments have been run the file holds no entry and the README has no table, and that
state passes. A table without an entry, or an entry without a table, fails, and a figure that
differs is named by its measure and its experiment.
"""

from pathlib import Path

from test_experiment_results import ENTRIES, readme_with

from evals.experiment_results import RESULTS_FILE, column_title, read_entries, spread_problems

README = Path(__file__).resolve().parents[3] / "README.md"


def real_state():
    """The README and the entries as committed, or a made-up pair while the file holds none."""
    entries = read_entries(RESULTS_FILE)
    if entries:
        return README.read_text(encoding="utf-8"), entries
    return readme_with(ENTRIES), ENTRIES


def test_the_committed_file_is_one_the_reader_accepts():
    assert isinstance(read_entries(RESULTS_FILE), list)


def test_the_readmes_spread_table_matches_the_experiments_file():
    readme = README.read_text(encoding="utf-8")
    assert spread_problems(readme, read_entries(RESULTS_FILE)) == []


def plant(readme, entries):
    """Make the first column's Obligations found figure one too high, inside the spread table.

    The line is found from the spread table's own heading and rebuilt from its parsed cells, so a
    figure in any other table is never the one changed.
    """
    lines = readme.splitlines()
    heading = f"| Measure | {column_title(entries[0])}"
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    row = next(i for i in range(start, len(lines)) if lines[i].startswith("| Obligations found"))
    cells = [c.strip() for c in lines[row].strip().strip("|").split("|")]
    figure = entries[0].measures["obligations_found"]
    assert cells[1] == figure.text
    cells[1] = f"{figure.numerator + 1} of {figure.denominator}"
    lines[row] = "| " + " | ".join(cells) + " |"
    return "\n".join(lines) + "\n"


MEASURE_TABLE = (
    "| Measure | Starter's agent, all 10 sections | This engine, section 7 |\n"
    "| --- | --- | --- |\n"
    "| Obligations found, of the labelled obligations in scope | 37 of 39 | 4 of 4 |\n\n"
)


def test_a_planted_wrong_figure_in_the_table_turns_the_check_red():
    readme, entries = real_state()
    assert spread_problems(readme, entries) == []
    wrong = plant(readme, entries)
    assert wrong != readme
    problems = spread_problems(wrong, entries)
    assert len(problems) == 1
    assert f"'Obligations found', {column_title(entries[0])}, says" in problems[0]


def test_the_planted_figure_lands_in_the_spread_table_when_the_measure_table_holds_it_too():
    entries = ENTRIES
    readme = MEASURE_TABLE + readme_with(entries)
    assert "| 37 of 39 | 4 of 4 |" in readme
    assert spread_problems(readme, entries) == []
    wrong = plant(readme, entries)
    assert wrong.startswith(MEASURE_TABLE)
    problems = spread_problems(wrong, entries)
    assert len(problems) == 1
    assert f"'Obligations found', {column_title(entries[0])}, says 38 of 39" in problems[0]


def test_a_correct_readme_whose_measure_table_holds_the_same_figure_passes():
    readme = MEASURE_TABLE + readme_with(ENTRIES)
    assert spread_problems(readme, ENTRIES) == []
