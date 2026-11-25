"""Tests of the experiments file and of the check that ties the README's spread table to it."""

import json

import pytest

from evals.evaluators import MEASURE_KEYS
from evals.experiment_results import (
    DuplicateExperimentError,
    ExperimentEntry,
    ExperimentFileError,
    Figure,
    append_entry,
    column_title,
    read_entries,
    spread_problems,
)

POPULATIONS = {key: f"population of {key}" for key in MEASURE_KEYS}


def entry(agent="starter", dataset="sections", repetition=1, suffix="1a2b3c4d", **found):
    figures = {
        "obligations_found": Figure(37, 39, POPULATIONS["obligations_found"]),
        "invented_obligations": Figure(7, 45, POPULATIONS["invented_obligations"]),
        "quotes_word_for_word": Figure(45, 45, POPULATIONS["quotes_word_for_word"]),
        "deadlines_as_written": Figure(28, 28, POPULATIONS["deadlines_as_written"]),
        "deadlines_matched": Figure(15, 15, POPULATIONS["deadlines_matched"]),
        "paragraph_recall": Figure(23, 23, POPULATIONS["paragraph_recall"]),
        "paragraph_precision": Figure(23, 29, POPULATIONS["paragraph_precision"]),
    }
    figures.update({k: Figure(*v, POPULATIONS[k]) for k, v in found.items()})
    return ExperimentEntry(
        name=f"{agent}-{dataset}-r{repetition}-{suffix}",
        experiment_id=f"0b1c2d3e-0000-4000-8000-{agent[:1]}{dataset[:1]}{repetition:010d}",
        agent=agent,
        dataset=dataset,
        repetition=repetition,
        ran_at="2026-11-25T10:00:00+00:00",
        examples=10,
        failed_examples=(),
        model="claude-sonnet-5-5",
        effort="medium",
        prompt_version="section-1a2b3c4d",
        measures=figures,
    )


def table(entries, *, edit=None):
    """A README spread table for the entries, with one cell optionally changed."""
    labels = {
        "obligations_found": "Obligations found, of the labelled obligations in scope",
        "invented_obligations": "Invented obligations, of all predicted (lower is better)",
        "quotes_word_for_word": "Quotes word for word, of those citing a paragraph in scope",
        "deadlines_as_written": "Deadlines as written, of predicted obligations with a deadline",
        "deadlines_matched": "Deadlines matched, of matched obligations with a labelled deadline",
        "paragraph_recall": "Paragraph recall, of paragraphs holding a labelled obligation",
        "paragraph_precision": "Paragraph precision, of paragraphs holding a predicted obligation",
    }
    titles = [column_title(e) for e in entries]
    lines = ["| Measure | " + " | ".join(titles) + " |"]
    lines.append("| --- |" + " --- |" * len(titles))
    for key in MEASURE_KEYS:
        cells = " | ".join(e.measures[key].text for e in entries)
        lines.append(f"| {labels[key]} | {cells} |")
    lines += ["", *(f"- {column_title(e)}: `{e.name}`, id `{e.experiment_id}`" for e in entries)]
    text = "\n".join(lines)
    return text.replace(*edit, 1) if edit else text


README = "# Title\n\nSome words.\n\n{table}\n\nMore words.\n"


def readme_with(entries, **kw):
    return README.format(table=table(entries, **kw))


ENTRIES = [entry(repetition=1, suffix="aaaa1111"), entry(repetition=2, suffix="bbbb2222")]


def test_a_figure_reads_as_its_counts_and_none_in_scope_is_not_zero():
    assert Figure(37, 39, "x").text == "37 of 39"
    assert Figure(0, 0, "x").text == "none in scope"


def test_an_entry_goes_to_the_file_and_back_with_every_count():
    assert ExperimentEntry.from_json(ENTRIES[0].to_json()) == ENTRIES[0]


def test_a_missing_file_holds_no_entry_and_an_entry_is_kept_in_the_file(tmp_path):
    path = tmp_path / "experiments.json"
    assert read_entries(path) == []
    append_entry(path, ENTRIES[0])
    append_entry(path, ENTRIES[1])
    assert read_entries(path) == ENTRIES
    assert json.loads(path.read_text())["experiments"][0]["name"] == ENTRIES[0].name


def test_the_same_experiment_is_not_added_twice(tmp_path):
    path = tmp_path / "experiments.json"
    append_entry(path, ENTRIES[0])
    with pytest.raises(DuplicateExperimentError, match="starter, sections, repetition 1"):
        append_entry(path, entry(repetition=1, suffix="cccc3333"))
    assert read_entries(path) == [ENTRIES[0]]


@pytest.mark.parametrize("key", ["cost", "rate_limit", "usage", "tokens", "url"])
def test_a_file_with_a_key_the_entry_does_not_define_is_refused_by_its_name(tmp_path, key):
    path = tmp_path / "experiments.json"
    data = ENTRIES[0].to_json()
    data[key] = 1
    path.write_text(json.dumps({"experiments": [data]}))
    with pytest.raises(ExperimentFileError, match=f"'{key}'"):
        read_entries(path)


def test_a_file_that_is_not_json_or_has_the_wrong_shape_fails_in_words(tmp_path):
    path = tmp_path / "experiments.json"
    path.write_text("not json")
    with pytest.raises(ExperimentFileError, match="not valid JSON"):
        read_entries(path)
    path.write_text('{"runs": []}')
    with pytest.raises(ExperimentFileError, match="'experiments'"):
        read_entries(path)


def test_a_count_larger_than_its_total_is_refused_when_the_file_is_read(tmp_path):
    path = tmp_path / "experiments.json"
    data = ENTRIES[0].to_json()
    data["measures"]["obligations_found"]["numerator"] = 40
    path.write_text(json.dumps({"experiments": [data]}))
    with pytest.raises(ExperimentFileError, match="obligations_found"):
        read_entries(path)


def test_no_entry_and_no_table_agree():
    assert spread_problems(README.format(table="No table here."), []) == []


def test_a_table_that_matches_the_file_has_no_problem():
    assert spread_problems(readme_with(ENTRIES), ENTRIES) == []


def test_a_planted_wrong_figure_names_the_cell_that_differs():
    wrong = readme_with(ENTRIES, edit=("| 37 of 39 | 37 of 39 |", "| 37 of 39 | 38 of 39 |"))
    problems = spread_problems(wrong, ENTRIES)
    assert problems == [
        "README: 'Obligations found', Starter's agent, run 2, says 38 of 39; "
        "experiments.json holds 37 of 39."
    ]


def test_a_figure_in_the_first_column_is_named_in_that_column():
    wrong = readme_with(ENTRIES, edit=("| 37 of 39 |", "| 36 of 39 |"))
    (problem,) = spread_problems(wrong, ENTRIES)
    assert "Starter's agent, run 1" in problem and "says 36 of 39" in problem


def test_a_table_with_no_entry_in_the_file_fails():
    problems = spread_problems(readme_with(ENTRIES), [])
    assert problems == ["The README has a spread table and experiments.json holds no entry."]


def test_an_entry_with_no_table_fails():
    problems = spread_problems(README.format(table="No table."), ENTRIES)
    assert problems == ["experiments.json holds 2 entries and the README has no spread table."]


def test_a_column_for_an_experiment_the_file_does_not_hold_is_named():
    third = entry(repetition=3, suffix="dddd4444")
    problems = spread_problems(readme_with([*ENTRIES, third]), ENTRIES)
    assert problems == [
        "README: the column 'Starter's agent, run 3' names no experiment in experiments.json."
    ]


def test_an_entry_with_no_column_is_named():
    third = entry(repetition=3, suffix="dddd4444")
    problems = spread_problems(readme_with(ENTRIES), [*ENTRIES, third])
    assert problems == [
        f"experiments.json: {third.name} has no column in the README's table.",
        f"README: the list under the table lacks the name of {third.name}.",
        f"README: the list under the table lacks the LangSmith id of {third.experiment_id}.",
    ]


def test_a_table_without_a_row_for_a_measure_names_the_measure():
    without = "\n".join(
        line
        for line in readme_with(ENTRIES).splitlines()
        if not line.startswith("| Paragraph recall")
    )
    problems = spread_problems(without, ENTRIES)
    assert problems == ["README: the spread table has no row for 'Paragraph recall'."]


def test_a_figure_that_is_not_a_count_is_named():
    wrong = readme_with(ENTRIES, edit=("| 23 of 29 |", "| about 80 per cent |"))
    (problem,) = spread_problems(wrong, ENTRIES)
    assert "says about 80 per cent" in problem and "holds 23 of 29" in problem


def test_the_ordinary_measure_table_is_not_taken_for_the_spread_table():
    ordinary = (
        "| Measure | Starter's agent, all 10 sections | This engine, section 7 |\n"
        "| --- | --- | --- |\n| Obligations found, of those | 35 of 39 | 4 of 4 |\n"
    )
    assert spread_problems(ordinary, []) == []


def test_a_row_with_fewer_figures_than_columns_is_named():
    short = readme_with(ENTRIES, edit=("| 23 of 29 | 23 of 29 |", "| 23 of 29 |"))
    (problem,) = spread_problems(short, ENTRIES)
    assert problem == "README: the row for 'Paragraph precision' holds 1 of the 2 figures it needs."


def test_the_columns_are_tied_to_the_file_by_agent_and_repetition_whatever_their_order():
    entries = [ENTRIES[1], ENTRIES[0]]
    assert spread_problems(readme_with(entries), ENTRIES) == []


def test_an_engine_column_and_a_whole_document_column_are_tied_to_their_entries():
    mixed = [
        entry(agent="engine", repetition=1, suffix="eeee0001"),
        entry(agent="engine", dataset="document", repetition=1, suffix="ffff0002"),
    ]
    readme = readme_with(mixed)
    assert "This engine, run 1" in readme and "This engine, whole document" in readme
    assert spread_problems(readme, mixed) == []
    swapped = readme.replace("This engine, run 1", "This engine, run 2", 1)
    assert spread_problems(swapped, mixed) == [
        "README: the column 'This engine, run 2' names no experiment in experiments.json.",
        f"experiments.json: {mixed[0].name} has no column in the README's table.",
    ]


def test_a_list_under_the_table_that_lacks_an_experiments_name_or_id_is_named():
    readme = readme_with(ENTRIES)
    no_name = readme.replace(ENTRIES[0].name, "something-else")
    assert spread_problems(no_name, ENTRIES) == [
        f"README: the list under the table lacks the name of {ENTRIES[0].name}."
    ]
    no_id = readme.replace(ENTRIES[1].experiment_id, "an-id")
    assert spread_problems(no_id, ENTRIES) == [
        f"README: the list under the table lacks the LangSmith id of {ENTRIES[1].experiment_id}."
    ]


def test_a_column_that_appears_twice_is_named():
    twice = readme_with(ENTRIES).replace("Starter's agent, run 2", "Starter's agent, run 1", 1)
    problems = spread_problems(twice, ENTRIES)
    assert "README: the column 'Starter's agent, run 1' appears more than once." in problems


def test_an_entry_names_the_model_effort_and_prompt_version_it_ran_with(tmp_path):
    path = tmp_path / "experiments.json"
    append_entry(path, ENTRIES[0])
    kept = json.loads(path.read_text())["experiments"][0]
    assert (kept["model"], kept["effort"], kept["prompt_version"]) == (
        "claude-sonnet-5-5",
        "medium",
        "section-1a2b3c4d",
    )


def test_an_entry_without_its_model_is_refused_by_the_key(tmp_path):
    path = tmp_path / "experiments.json"
    data = ENTRIES[0].to_json()
    del data["model"]
    path.write_text(json.dumps({"experiments": [data]}))
    with pytest.raises(ExperimentFileError, match="'model'"):
        read_entries(path)
