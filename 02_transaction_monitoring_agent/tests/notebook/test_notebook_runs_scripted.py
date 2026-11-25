"""The notebooks run top to bottom, record and replay, on a stand-in for the model: no live call."""

from __future__ import annotations

import os
import re

import pytest
from notebook_support import (
    MODULES,
    NAMES,
    STARTER_CELLS,
    NotebookCellError,
    execute_notebook,
    kernel_env,
    load,
    stand_in_for_claude,
    text_of,
)

needs_run = pytest.mark.skipif(
    os.environ.get("NOTEBOOK_RUN") != "1",
    reason="running a notebook starts a kernel; set NOTEBOOK_RUN=1 or run `make notebook`",
)
KEY_ORDER_LINE = re.compile(r"^\s{4}(transaction_id|risk_score): .*$")


def normal(cell):
    """The text of a cell with its tool-call argument lines in one order.

    A record run and a replay run of the stand-in write a tool call's arguments in different orders,
    so this comparison, between those two runs only, ignores the order of the lines of such a cell.
    """
    lines = text_of(cell).splitlines()
    return "\n".join(sorted(lines) if any(KEY_ORDER_LINE.match(line) for line in lines) else lines)


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    """Run all three notebooks in record mode on the stand-in, then in replay mode."""
    root = tmp_path_factory.mktemp("scripted")
    recordings = root / "recordings"
    bin_dir = stand_in_for_claude(root / "bin")
    patch = pytest.MonkeyPatch()
    try:
        kernel_env(patch, backend="record", recordings=recordings, bin_dir=bin_dir)
        first = {name: execute_notebook(load(name), cwd=MODULES) for name in NAMES}
        kernel_env(patch, backend="replay", recordings=recordings)
        patch.setenv("PATH", "/usr/bin:/bin")
        second = {name: execute_notebook(load(name), cwd=MODULES) for name in NAMES}
    finally:
        patch.undo()
    return first, second, recordings


@needs_run
def test_every_notebook_runs_top_to_bottom_in_record_mode_and_again_on_replay(recorded):
    first, second, recordings = recorded
    for name in NAMES:
        assert {m for _, m in first[name].call_log} <= {"record", "reused"}, name
        assert {m for _, m in second[name].call_log} == {"replay"}, name
    live = sum(m == "record" for name in NAMES for _, m in first[name].call_log)
    assert live == len(list(recordings.glob("*.json")))


@needs_run
def test_a_replay_gives_the_outputs_of_the_recorded_run_cell_for_cell(recorded):
    first, second, _ = recorded
    for name in NAMES:
        before = [normal(c) for c in first[name].notebook.cells if c.cell_type == "code"]
        after = [normal(c) for c in second[name].notebook.cells if c.cell_type == "code"]
        drifted = [n for n, (old, new) in enumerate(zip(before, after, strict=True)) if old != new]
        assert not drifted, (name, drifted)


@needs_run
def test_every_call_the_replay_made_is_a_file_of_the_recordings_folder(recorded):
    _, second, recordings = recorded
    for name in NAMES:
        assert all((recordings / f"{key}.json").is_file() for key, _ in second[name].call_log)


@needs_run
def test_the_langsmith_steps_say_so_in_one_sentence_and_do_nothing_without_a_key(recorded):
    _, second, _ = recorded
    sentence = "This step needs LangSmith: set LANGSMITH_API_KEY and LANGSMITH_TRACING=true"
    second_nb = second[NAMES[1]].notebook
    for index in (3, 11, 13):
        assert text_of(second_nb.cells[index]).startswith(sentence), index
    third = second[NAMES[2]].notebook
    for index in (2, 6, 10, 12, 18):
        assert text_of(third.cells[index]).startswith(sentence), index


@needs_run
def test_the_first_notebook_accounts_for_all_fifteen_transactions_and_decides_nothing(recorded):
    _, second, _ = recorded
    printed = "\n".join(
        text_of(c)
        for c in second[NAMES[0]].notebook.cells[STARTER_CELLS[NAMES[0]] :]
        if c.cell_type == "code"
    )
    assert "15 of 15 transactions of the starter's data accounted for across 2 runs" in printed
    assert printed.count("decisions made here") == 2 and "0 decisions made here" in printed
    assert (
        "units accounted for" in printed
        and "Assessments that passed every plain-code check" in printed
    )


@needs_run
def test_the_notebooks_stop_by_name_when_a_recording_is_missing(tmp_path, monkeypatch):
    empty = tmp_path / "recordings"
    empty.mkdir()
    kernel_env(monkeypatch, backend="replay", recordings=empty)
    with pytest.raises(NotebookCellError) as caught:
        execute_notebook(load(NAMES[0]), cwd=MODULES)
    assert caught.value.error_name == "ReplayMissError"
    assert "no recording" in str(caught.value)
    assert caught.value.index == 3


@needs_run
def test_the_runner_names_the_cell_that_raises(tmp_path):
    import nbformat

    notebook = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_code_cell("value = 1"),
            nbformat.v4.new_code_cell("raise ValueError('planted failure')"),
            nbformat.v4.new_code_cell("print('not reached')"),
        ]
    )
    with pytest.raises(NotebookCellError) as caught:
        execute_notebook(notebook, cwd=tmp_path)
    assert caught.value.index == 1 and "planted failure" in str(caught.value)
    assert notebook.cells[2].outputs == []
