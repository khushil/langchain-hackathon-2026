"""The outputs the notebooks carry are what the saved calls give on a new run with no key."""

from __future__ import annotations

import os

import pytest
from notebook_support import NAMES, TOPIC, execute_notebook, kernel_env, load, text_of

needs_run = pytest.mark.skipif(
    os.environ.get("NOTEBOOK_RUN") != "1",
    reason="running a notebook starts a kernel; set NOTEBOOK_RUN=1 or run `make notebook`",
)
LEAKS = ("smith.langchain", "http://", "https://", "/home/", "Traceback", "LANGSMITH_API_KEY=")
SENTENCE = "This step needs LangSmith: set LANGSMITH_API_KEY and LANGSMITH_TRACING=true"


def code_cells(name: str) -> list:
    return [c for c in load(name).cells if c.cell_type == "code"]


@pytest.mark.parametrize("name", NAMES)
def test_every_code_cell_was_run_and_none_ended_in_an_error(name):
    for number, cell in enumerate(code_cells(name)):
        assert cell.execution_count is not None, (name, number)
        assert not [o for o in cell.outputs if o.output_type == "error"], (name, number)


@pytest.mark.parametrize("name", NAMES)
def test_no_output_holds_a_link_a_path_of_this_machine_or_a_key(name):
    for number, cell in enumerate(code_cells(name)):
        shown = text_of(cell)
        for leak in LEAKS:
            assert leak not in shown, (name, number, leak)


def test_the_langsmith_steps_carry_their_one_sentence_because_the_outputs_were_made_with_no_key():
    counts = {}
    for name in NAMES:
        counts[name] = sum(text_of(c).startswith(SENTENCE) for c in code_cells(name))
    assert counts == {NAMES[0]: 0, NAMES[1]: 3, NAMES[2]: 5}


@needs_run
def test_a_new_replay_gives_the_outputs_the_notebooks_carry(monkeypatch):
    kernel_env(monkeypatch, backend="replay", recordings=TOPIC / "recordings")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    for name in NAMES:
        carried = [text_of(c) for c in code_cells(name)]
        again = execute_notebook(load(name), cwd=TOPIC / "modules")
        fresh = [text_of(c) for c in again.notebook.cells if c.cell_type == "code"]
        drifted = [n for n, (old, new) in enumerate(zip(carried, fresh, strict=True)) if old != new]
        assert not drifted, (name, drifted)
        assert {mode for _, mode in again.call_log} <= {"replay"}, name
