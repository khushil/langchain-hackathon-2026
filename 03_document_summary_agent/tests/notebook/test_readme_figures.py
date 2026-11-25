"""The README's measure table and the sentences that quote it match what the notebook printed.

The committed notebook holds the output of the run the application and the notebook replay: the
starter's agent beside this engine over all ten sections, scored by the same code. The README
quotes those figures, and beside them the figures of the first whole-document run, which was made
before the obligation marker check existed and is not replayed. A new recording that changes a
figure cannot leave the README stale: this test names each figure that differs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from review_app.seed_fixture import QUESTIONS

TOPIC = Path(__file__).resolve().parents[2]
REPO = TOPIC.parent
NOTEBOOK = TOPIC / "modules" / "01_document_summary_agent.ipynb"
README = REPO / "README.md"
GUIDE = REPO / "docs" / "user-guide.md"

MEASURES = {
    "Obligations found": "obligations_found",
    "Invented obligations": "invented_obligations",
    "Quotes word for word": "quotes_word_for_word",
    "Deadlines as written": "deadlines_as_written",
    "Deadlines matched": "deadlines_matched",
    "Paragraph recall": "paragraph_recall",
    "Paragraph precision": "paragraph_precision",
}
COLUMNS = (
    "starter's agent",
    "this engine",
    "starter's agent, first run",
    "this engine, first run",
)
FIGURE = re.compile(r"(\d+) of (\d+)")

# The lines the first whole-document run printed where the notebook prints its side-by-side
# scores, copied as they were. The run was recorded from 00:02 to 00:06 UTC on 25 November 2026,
# before the obligation marker check was added, and its recordings are not kept in this
# repository. Only the figures are copied; the replayed run's figures are read from the notebook.
FIRST_RUN_LINES = """\
10 of 10 sections returned a summary

obligations_found
    starter's agent            36 of 39 labelled obligations in scope
    this repository's engine   35 of 39 labelled obligations in scope
invented_obligations
    starter's agent            4 of 42 predicted obligations
    this repository's engine   3 of 40 predicted obligations
quotes_word_for_word
    starter's agent            42 of 42 predicted obligations citing a paragraph in scope
    this repository's engine   40 of 40 predicted obligations citing a paragraph in scope
deadlines_as_written
    starter's agent            25 of 25 predicted obligations with a deadline
    this repository's engine   21 of 21 predicted obligations with a deadline
deadlines_matched
    starter's agent            16 of 16 matched obligations whose labelled deadline is not empty
    this repository's engine   15 of 15 matched obligations whose labelled deadline is not empty
paragraph_recall
    starter's agent            23 of 23 paragraphs holding a labelled obligation
    this repository's engine   22 of 23 paragraphs holding a labelled obligation
paragraph_precision
    starter's agent            23 of 27 paragraphs holding a predicted obligation
    this repository's engine   22 of 25 paragraphs holding a predicted obligation

PS26-4/section/9   starter's agent 1 of 1 labelled obligations in scope
                   this engine     0 of 1 labelled obligations in scope
"""

TEXT_SENTENCES = {
    "replayed starter": re.compile(
        r"In the replayed run the starter's agent missed (\d+) of (\d+) labelled obligations "
        r"and (\d+) of the (\d+) obligations it returned match no label"
    ),
    "replayed engine": re.compile(
        r"this engine missed (\d+) of (\d+) and (\d+) of the (\d+) it returned match no label"
    ),
    "first starter": re.compile(
        r"In the first run the starter's agent missed (\d+) of (\d+) and (\d+) of its (\d+) "
        r"match no label"
    ),
    "first engine": re.compile(
        r"the engine missed (\d+) of (\d+) and (\d+) of its (\d+) match no label"
    ),
}
RUN_SENTENCE = re.compile(
    r"In the replayed run the engine read (\d+) facts and all (\d+) passed their checks, "
    r"(\d+) of (\d+) paragraphs were accounted for, the brief has (\d+) statements, "
    r"(\d+) open questions went to the reviewer, and the marker check sent (\d+) paragraphs "
    r"for a second read"
)


SAVED_CALLS = re.compile(r"(\d+) saved (?:model )?calls")
SEED_QUESTIONS = re.compile(r"her answers to (\w+) open questions and her assumption for (\w+)")
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
REQUIRED_SENTENCES = {
    "the check was added after the first run missed paragraph 9.3": (
        "was added after the first whole-document run missed paragraph 9.3"
    ),
    "the replayed run sent no paragraph back": "the check sent no paragraph back for a second read",
    "one recorded run is one draw": "One recorded run is one draw.",
}


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


def side_by_side(text: str) -> dict[str, tuple[str, str]]:
    """Read the starter's and the engine's figure for each measure from a side-by-side print.

    Args:
        text: What the notebook's scoring cell printed for the two agents.

    Returns:
        For each measure key, the starter's figure and the engine's, each as "N of M".

    Raises:
        FiguresNotFoundError: If a measure is not printed for both agents.
    """
    found = {}
    for key in MEASURES.values():
        both = re.search(
            rf"^{key}\n\s+starter's agent\s+(\d+ of \d+).*\n"
            rf"\s+this repository's engine\s+(\d+ of \d+)",
            text,
            re.M,
        )
        if not both:
            raise FiguresNotFoundError(f"The scoring output does not print {key} for both agents.")
        found[key] = (both[1], both[2])
    return found


def printed_figures(notebook: dict) -> dict[str, dict[str, str]]:
    """Read the figures of the replayed run and of the first run.

    Args:
        notebook: The notebook as JSON.

    Returns:
        For each measure key, its figure in each of the four columns, as "N of M".

    Raises:
        FiguresNotFoundError: If the side-by-side output is not found once, or lacks a measure.
    """
    scores = [
        t for t in cell_outputs(notebook) if re.search(r"^obligations_found\n\s+starter", t, re.M)
    ]
    if len(scores) != 1:
        raise FiguresNotFoundError(
            f"The notebook holds {len(scores)} side-by-side scoring outputs; it must hold one."
        )
    now, first = side_by_side(scores[0]), side_by_side(FIRST_RUN_LINES)
    return {
        key: dict(zip(COLUMNS, (*now[key], *first[key]), strict=True)) for key in MEASURES.values()
    }


def run_figures(notebook: dict) -> dict[str, int]:
    """Read the counts of the replayed run that the README's text repeats.

    Args:
        notebook: The notebook as JSON.

    Returns:
        The facts read and passed, the paragraphs accounted for and read, the statements, the
        open questions and the paragraphs sent for a second read.

    Raises:
        FiguresNotFoundError: If a printed line is missing.
    """
    printed = "\n".join(cell_outputs(notebook))
    patterns = {
        "passed": r"Facts that passed every plain-code check: (\d+) of (\d+)",
        "cited": r"Distinct facts cited: (\d+)",
        "accounted": r"\(PS26-4\): (\d+) of (\d+) units accounted for",
        "statements": r"Statements in the brief: (\d+)",
        "questions": r"Open questions for the reviewer: (\d+)",
        "second": r"Second reads: (\d+) paragraphs sent back",
        "kinds": r"Facts by kind: (.*)",
    }
    found = {}
    for name, pattern in patterns.items():
        match = re.search(pattern, printed)
        if not match:
            raise FiguresNotFoundError(f"The notebook does not print the line for {name}.")
        found[name] = match.groups()
    if "[para:9.3] passed" not in printed:
        raise FiguresNotFoundError("The notebook does not print a passed fact for paragraph 9.3.")
    kinds = {kind: int(n) for n, kind in re.findall(r"(\d+) (\w+)(?:, |$)", found["kinds"][0])}
    return {
        "profile": kinds["firm_attribute"] + kinds["provider_attribute"],
        "facts": int(found["passed"][1]),
        "cited": int(found["cited"][0]),
        "passed": int(found["passed"][0]),
        "accounted": int(found["accounted"][0]),
        "paragraphs": int(found["accounted"][1]),
        "statements": int(found["statements"][0]),
        "questions": int(found["questions"][0]),
        "second": int(found["second"][0]),
    }


def measure_table_rows(readme: str) -> list[str]:
    """Return the body rows of the README's measure table, and of no other table.

    The measure table is the first table whose header reads "Measure" and then "Starter's agent".
    The spread table of repeated runs below it names runs in its header ("Starter's agent, run 1")
    and starts its rows with the same measure names, so it must not be read as this one.

    Args:
        readme: The README's text.

    Returns:
        The table's lines after its header, separator row included; empty when there is no table.
    """
    lines = readme.splitlines()
    for at, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) > 2 and cells[0] == "Measure" and cells[1] == "Starter's agent":
            block = []
            for row in lines[at + 1 :]:
                if not row.startswith("|"):
                    break
                block.append(row)
            return block
    return []


def readme_table(readme: str) -> dict[str, dict[str, str]]:
    """Read the README's measure table.

    Args:
        readme: The README's text.

    Returns:
        For each measure key, its figure in each of the four columns.

    Raises:
        FiguresNotFoundError: If a measure has no row or a row has no four figures.
    """
    rows = measure_table_rows(readme)
    found: dict[str, dict[str, str]] = {}
    for label, key in MEASURES.items():
        matches = [r for r in rows if r.split("|")[1].strip().startswith(label)]
        if len(matches) != 1:
            raise FiguresNotFoundError(
                f"The README's measure table has {len(matches)} rows for '{label}'; it needs one."
            )
        cells = [c.strip() for c in matches[0].strip().strip("|").split("|")[1:]]
        if len(cells) != 4 or not all(FIGURE.fullmatch(c) for c in cells):
            raise FiguresNotFoundError(f"The row for '{label}' does not hold four figures.")
        found[key] = dict(zip(COLUMNS, cells, strict=True))
    return found


def sentence_figures(readme: str, name: str) -> tuple[int, ...]:
    """Read the four numbers of one README sentence on missed and unmatched obligations."""
    match = TEXT_SENTENCES[name].search(readme)
    if not match:
        raise FiguresNotFoundError(
            f"The README no longer has its sentence on the {name} agent's missed and "
            "unmatched obligations."
        )
    return tuple(int(g) for g in match.groups())


def claim_problems(readme: str) -> list[str]:
    """Name each README claim about the recordings, the seed or the run that does not hold.

    Args:
        readme: The README's text.

    Returns:
        One sentence for each claim that fails; empty when the README is current.

    Raises:
        FiguresNotFoundError: If the README no longer gives the recordings count or the seed's.
    """
    on_disk = len(list((TOPIC / "recordings").glob("*.json")))
    problems = [
        f"README: says {n} saved calls; the recordings folder holds {on_disk}."
        for n in SAVED_CALLS.findall(readme)
        if int(n) != on_disk
    ]
    seed = SEED_QUESTIONS.search(readme)
    if not SAVED_CALLS.search(readme) or not seed:
        raise FiguresNotFoundError("The README no longer gives the recordings or the seed counts.")
    answered = sum(1 for q in QUESTIONS if q.answer)
    accepted = sum(1 for q in QUESTIONS if q.assumption)
    if (WORDS[seed[1]], WORDS[seed[2]]) != (answered, accepted):
        problems.append(
            f"README: the seed's answers and assumptions are said to be {seed[1]} and {seed[2]}; "
            f"the fixture answers {answered} and accepts {accepted}."
        )
    problems += [
        f"README: the sentence that says {name} is missing."
        for name, phrase in REQUIRED_SENTENCES.items()
        if phrase not in readme
    ]
    return problems


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
    for name, column in (
        ("replayed starter", COLUMNS[0]),
        ("replayed engine", COLUMNS[1]),
        ("first starter", COLUMNS[2]),
        ("first engine", COLUMNS[3]),
    ):
        found, total = map(int, printed["obligations_found"][column].split(" of "))
        wrong, predicted = map(int, printed["invented_obligations"][column].split(" of "))
        said = sentence_figures(readme, name)
        if said != (total - found, total, wrong, predicted):
            problems.append(
                f"README: the sentence on the {name} agent says {said[0]} of {said[1]} missed and "
                f"{said[2]} of {said[3]} matching no label; the notebook printed "
                f"{total - found} of {total} and {wrong} of {predicted}."
            )
    ran = run_figures(notebook)
    run_said = RUN_SENTENCE.search(readme)
    if not run_said:
        raise FiguresNotFoundError("The README no longer says what the replayed run read.")
    said_run = tuple(int(g) for g in run_said.groups())
    wanted = (
        ran["facts"],
        ran["passed"],
        ran["accounted"],
        ran["paragraphs"],
        ran["statements"],
        ran["questions"],
        ran["second"],
    )
    if said_run != wanted:
        problems.append(
            f"README: the sentence on the replayed run says {said_run}; "
            f"the notebook printed {wanted}."
        )
    return problems + claim_problems(readme)


GUIDE_SENTENCES = {
    "answer": re.compile(
        r"has (\d+) statements resting on (\d+) facts\. (\d+) facts and (\d+) questions "
        r"still need your decision"
    ),
    "picture": re.compile(r'"(\d+) of (\d+) paragraphs of the document accounted for"'),
    "tiles": re.compile(
        r'as "0 of (\d+)", with the badge "Needs a person"\. '
        r'"Questions settled" shows "0 of (\d+)"'
    ),
    "profile": re.compile(
        r'"covering (\d+) facts", with your reason, '
        r'and the tile "Facts decided" reads "(\d+) of (\d+)"'
    ),
}


def guide_problems(guide: str, notebook: dict) -> list[str]:
    """Name every count the user guide gives for the seeded brief that the notebook did not print.

    Args:
        guide: The user guide's text.
        notebook: The notebook as JSON.

    Returns:
        One sentence for each count that differs; empty when the guide is current.

    Raises:
        FiguresNotFoundError: If the guide lacks one of the sentences that quote a count.
    """
    ran = run_figures(notebook)
    wanted = {
        "answer": (ran["statements"], ran["cited"], ran["cited"], ran["questions"]),
        "picture": (ran["accounted"], ran["paragraphs"]),
        "tiles": (ran["cited"], ran["questions"]),
        "profile": (ran["profile"], ran["profile"], ran["cited"]),
    }
    problems = []
    for name, pattern in GUIDE_SENTENCES.items():
        match = pattern.search(guide)
        if not match:
            raise FiguresNotFoundError(f"The guide no longer has its '{name}' sentence.")
        said = tuple(int(g) for g in match.groups())
        if said != wanted[name]:
            problems.append(
                f"Guide: the '{name}' sentence says {said}; the notebook printed {wanted[name]}."
            )
    return problems


@pytest.fixture(scope="module")
def guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


def test_the_readmes_measure_table_and_sentences_match_what_the_notebook_printed(readme, notebook):
    assert figure_problems(readme, notebook) == []


def test_the_notebook_prints_all_seven_measures_for_both_agents_and_the_first_run_is_kept(notebook):
    printed = printed_figures(notebook)
    assert set(printed) == set(MEASURES.values())
    assert all(set(v) == set(COLUMNS) for v in printed.values())
    assert printed["obligations_found"][COLUMNS[2]] == "36 of 39"
    assert printed["paragraph_recall"][COLUMNS[3]] == "22 of 23"


def test_the_replayed_run_covers_the_whole_document(notebook):
    ran = run_figures(notebook)
    assert ran["paragraphs"] == 48 and ran["accounted"] == ran["paragraphs"]
    assert ran["facts"] == ran["passed"]


def test_a_planted_figure_in_the_table_is_named(readme, notebook):
    changed = readme.replace("| 26 of 26 |", "| 24 of 24 |", 1)
    assert changed != readme
    problems = figure_problems(changed, notebook)
    assert len(problems) == 1
    assert "'Deadlines as written', this engine, says 24 of 24" in problems[0]
    assert "printed 26 of 26" in problems[0]


def test_a_planted_figure_in_each_column_is_named_in_its_column(readme, notebook):
    printed = printed_figures(notebook)
    row = next(line for line in readme.splitlines() if line.startswith("| Paragraph recall"))
    for position, column in enumerate(COLUMNS):
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        cells[position + 1] = "9 of 9"
        changed = readme.replace(row, "| " + " | ".join(cells) + " |")
        problems = figure_problems(changed, notebook)
        assert len(problems) == 1, problems
        assert f"'Paragraph recall', {column}, says 9 of 9" in problems[0]
        assert printed["paragraph_recall"][column] in problems[0]


def test_a_planted_figure_in_each_sentence_is_named(readme, notebook):
    for name in TEXT_SENTENCES:
        match = TEXT_SENTENCES[name].search(readme)
        old = match.group(0)
        new = old.replace(f"missed {match[1]} of", "missed 99 of", 1)
        problems = figure_problems(readme.replace(old, new, 1), notebook)
        assert len(problems) == 1 and f"the {name} agent says 99 of" in problems[0], problems


def test_a_planted_figure_in_the_replayed_run_sentence_is_named(readme, notebook):
    old = RUN_SENTENCE.search(readme).group(0)
    for number in re.findall(r"\d+", old):
        new = re.sub(rf"\b{number}\b", "77", old, count=1)
        problems = figure_problems(readme.replace(old, new, 1), notebook)
        assert len(problems) == 1 and "the replayed run says" in problems[0], (number, problems)


def test_a_readme_with_a_measure_row_removed_fails_in_words(readme, notebook):
    kept = "\n".join(
        line for line in readme.splitlines() if not line.startswith("| Paragraph recall")
    )
    with pytest.raises(FiguresNotFoundError, match="0 rows for 'Paragraph recall'"):
        figure_problems(kept, notebook)


def test_a_readme_that_loses_a_sentence_fails_in_words(readme, notebook):
    old = RUN_SENTENCE.search(readme).group(0)
    with pytest.raises(FiguresNotFoundError, match="no longer says what the replayed run read"):
        figure_problems(readme.replace(old, "The run read facts."), notebook)
    first = TEXT_SENTENCES["first engine"].search(readme).group(0)
    with pytest.raises(FiguresNotFoundError, match="first engine agent's missed"):
        figure_problems(readme.replace(first, "the engine did less"), notebook)


def test_a_notebook_without_the_scoring_output_fails_in_words(readme, notebook):
    stripped = {
        **notebook,
        "cells": [
            {**c, "outputs": []} if c["cell_type"] == "code" else c for c in notebook["cells"]
        ],
    }
    with pytest.raises(FiguresNotFoundError, match="it must hold one"):
        figure_problems(readme, stripped)


def test_the_first_runs_copy_has_a_figure_for_every_measure_and_names_paragraph_nine_three():
    assert set(side_by_side(FIRST_RUN_LINES)) == set(MEASURES.values())
    assert "0 of 1 labelled obligations in scope" in FIRST_RUN_LINES


def test_the_guides_counts_for_the_seeded_brief_match_what_the_notebook_printed(guide, notebook):
    assert guide_problems(guide, notebook) == []


def test_a_planted_count_in_each_guide_sentence_is_named(guide, notebook):
    for name, pattern in GUIDE_SENTENCES.items():
        found = pattern.search(guide)
        old = found.group(0)
        start, end = found.span(1)
        new = old[: start - found.start()] + "99" + old[end - found.start() :]
        problems = guide_problems(guide.replace(old, new, 1), notebook)
        assert len(problems) == 1 and f"the '{name}' sentence says" in problems[0], problems


def test_a_guide_that_loses_a_sentence_fails_in_words(guide, notebook):
    old = GUIDE_SENTENCES["picture"].search(guide).group(0)
    with pytest.raises(FiguresNotFoundError, match="no longer has its 'picture' sentence"):
        guide_problems(guide.replace(old, '"all paragraphs"'), notebook)


def test_the_recordings_count_the_readme_gives_is_the_count_on_disk(readme):
    on_disk = len(list((TOPIC / "recordings").glob("*.json")))
    said = SAVED_CALLS.findall(readme)
    assert said and {int(n) for n in said} == {on_disk}


def test_a_planted_recordings_count_is_named_wherever_it_is_written(readme, notebook):
    for match in SAVED_CALLS.finditer(readme):
        wrong = readme[: match.start(1)] + "99" + readme[match.end(1) :]
        problems = claim_problems(wrong)
        assert len(problems) == 1 and "says 99 saved calls" in problems[0], problems


def test_the_seeds_answered_and_accepted_counts_in_the_readme_are_the_fixtures(readme):
    answered = sum(1 for q in QUESTIONS if q.answer)
    accepted = sum(1 for q in QUESTIONS if q.assumption)
    said = SEED_QUESTIONS.search(readme)
    assert (WORDS[said[1]], WORDS[said[2]]) == (answered, accepted) == (3, 1)


def test_a_planted_seed_count_in_the_readme_is_named(readme):
    for old, new in (
        ("answers to three", "answers to two"),
        ("assumption for one", "assumption for two"),
    ):
        assert old in readme
        problems = claim_problems(readme.replace(old, new, 1))
        assert len(problems) == 1 and "the seed" in problems[0], problems


def test_each_required_sentence_is_in_the_readme_and_dropping_it_turns_the_test_red(readme):
    assert claim_problems(readme) == []
    for name, phrase in REQUIRED_SENTENCES.items():
        assert phrase in readme, name
        problems = claim_problems(readme.replace(phrase, "", 1))
        assert problems == [f"README: the sentence that says {name} is missing."], problems


def test_the_guides_fact_counts_follow_the_facts_the_brief_cites_not_the_facts_read(
    guide, notebook
):
    fewer = json.loads(
        json.dumps(notebook).replace("Distinct facts cited: 57", "Distinct facts cited: 56")
    )
    problems = guide_problems(guide, fewer)
    assert len(problems) == 3 and all("56" in p for p in problems), problems


def test_a_spread_table_after_the_measure_table_is_not_read_as_it(readme, notebook):
    spread = (
        "\n| Measure | Starter's agent, run 1 |\n| --- | --- |\n"
        "| Obligations found | 1 of 39 |\n| Invented obligations | 1 of 2 |\n"
    )
    assert figure_problems(readme + spread, notebook) == []
