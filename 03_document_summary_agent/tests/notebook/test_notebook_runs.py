"""Checks on the notebook: its shape on every run, and its run from top to bottom on replay.

The shape checks run in the default suite. Running the notebook starts a kernel and reads the
recordings folder, so those tests run only when ``NOTEBOOK_RUN=1``, as ``make notebook`` sets it.
A run uses ``MODEL_BACKEND=replay`` and no tracing, so it needs no key and makes no live call.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import nbformat
import pytest
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

TOPIC = Path(__file__).resolve().parents[2]
REPO = TOPIC.parent
NOTEBOOK = TOPIC / "modules" / "01_document_summary_agent.ipynb"
STARTER_CELLS = 23
CELL_TIMEOUT_S = 600

needs_run = pytest.mark.skipif(
    os.environ.get("NOTEBOOK_RUN") != "1",
    reason="running the notebook starts a kernel; set NOTEBOOK_RUN=1 or run `make notebook`",
)

# Tokens a markdown cell of ours may hold that contain a digit: the document and the firm by
# their keys, and the starter's step numbers.
ALLOWED_DIGIT_TOKENS = re.compile(r"PS26-4|FIRM-001|[Ss]tep \d")
LIST_MARKER = re.compile(r"(?m)^\s*\d+\. ")


class NotebookCellError(Exception):
    """A cell raised while the notebook ran; the message names the cell and what it raised."""

    def __init__(self, index: int, first_line: str, error_name: str, error_value: str) -> None:
        self.index = index
        self.error_name = error_name
        super().__init__(f"Cell {index} ({first_line!r}) raised {error_name}: {error_value}")


@dataclass(frozen=True)
class RunResult:
    """What a run of a notebook left behind."""

    notebook: nbformat.NotebookNode
    call_log: list[tuple[str, str]]
    """The model calls the kernel made, each as (request hash, mode); empty without the adapter."""


CALL_LOG_CELL = """
import json
try:
    from fsi_common.model import call_records
    log = [[r.request_hash, r.mode] for r in call_records()]
except ImportError:
    log = []
print("CALL_LOG " + json.dumps(log))
"""


def _first_line(source: str) -> str:
    lines = source.strip().splitlines()
    return lines[0][:70] if lines else ""


def _text_of(cell: nbformat.NotebookNode) -> str:
    parts = []
    for output in cell.get("outputs", []):
        if output.output_type == "stream":
            parts.append(output.text)
        elif output.output_type in ("execute_result", "display_data"):
            parts.append(output.data.get("text/plain", ""))
    return "".join(parts)


def execute_notebook(notebook: nbformat.NotebookNode, *, cwd: Path) -> RunResult:
    """Run every code cell in order in one kernel, stopping at the first cell that raises.

    Args:
        notebook: The notebook to run; its cells receive their outputs.
        cwd: The folder the kernel starts in.

    Returns:
        The executed notebook and the model calls the kernel made.

    Raises:
        NotebookCellError: If a cell raises, naming the cell, the error and its message.
    """
    client = NotebookClient(
        notebook,
        timeout=CELL_TIMEOUT_S,
        kernel_name="python3",
        resources={"metadata": {"path": str(cwd)}},
    )
    with client.setup_kernel():
        for index, cell in enumerate(notebook.cells):
            if cell.cell_type != "code":
                continue
            try:
                client.execute_cell(cell, index)
            except CellExecutionError as error:
                raise NotebookCellError(
                    index, _first_line(cell.source), error.ename, error.evalue
                ) from error
        log_cell = nbformat.v4.new_code_cell(CALL_LOG_CELL)
        notebook.cells.append(log_cell)
        client.execute_cell(log_cell, len(notebook.cells) - 1)
        notebook.cells.pop()
    marker = next(line for line in _text_of(log_cell).splitlines() if line.startswith("CALL_LOG "))
    return RunResult(notebook, [tuple(pair) for pair in json.loads(marker[len("CALL_LOG ") :])])


def _replay_env(monkeypatch: pytest.MonkeyPatch, recordings: Path) -> None:
    """Point the kernel at replay, no tracing, the given recordings and the shared member."""
    monkeypatch.setenv("MODEL_BACKEND", "replay")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("MODEL_RECORDINGS_DIR", str(recordings))
    path = [str(REPO / "fsi_common"), os.environ.get("PYTHONPATH", "")]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(part for part in path if part))


def _load() -> nbformat.NotebookNode:
    return nbformat.read(NOTEBOOK, as_version=4)


def _code(notebook: nbformat.NotebookNode) -> list[str]:
    return [c.source for c in notebook.cells if c.cell_type == "code"]


# Shape checks, on every run of the suite.


def test_notebook_is_valid_nbformat_4_5_and_holds_the_outputs_of_its_recorded_run():
    notebook = _load()
    nbformat.validate(notebook)
    assert (notebook.nbformat, notebook.nbformat_minor) == (4, 5)
    code = [c for c in notebook.cells if c.cell_type == "code"]
    printing = [c for c in code if "print(" in c.source]
    assert printing and all(c.outputs for c in printing), (
        "a printing cell lacks its recorded output"
    )
    assert not [o for c in code for o in c.outputs if o.output_type == "error"]


def test_notebook_adds_cells_after_the_starters_23_and_none_before():
    notebook = _load()
    assert len(notebook.cells) > STARTER_CELLS
    first_new = notebook.cells[STARTER_CELLS]
    assert first_new.cell_type == "markdown"
    assert first_new.source.startswith("## ")
    assert "Document summary agent" in notebook.cells[0].source


def test_starter_cells_choose_their_model_through_get_model_only():
    cells = _load().cells[:STARTER_CELLS]
    code = "\n".join(c.source for c in cells if c.cell_type == "code")
    assert "init_chat_model" not in code
    assert 'get_model("orchestrator")' in cells[3].source
    assert 'model=get_model("section")' in cells[11].source


def test_notebook_builds_no_decision_and_no_sign_off():
    code = "\n".join(_code(_load()))
    assert "Decision" not in code
    assert "SignOff" not in code
    assert "sign_off" not in code
    assert ".submit(" not in code


def test_notebook_names_no_secret_and_sets_no_live_backend():
    code = "\n".join(_code(_load()))
    assert "LANGSMITH_KEY" not in code
    assert "MODEL_BACKEND" not in code
    assert "claude-code" not in code


def test_new_markdown_types_no_number_that_a_run_could_change():
    notebook = _load()
    new_markdown = [c.source for c in notebook.cells[STARTER_CELLS:] if c.cell_type == "markdown"]
    assert new_markdown, "the notebook adds no markdown after the starter's cells"
    for text in new_markdown:
        stripped = ALLOWED_DIGIT_TOKENS.sub("", LIST_MARKER.sub("", text))
        assert not re.search(r"\d", stripped), f"a number is typed in: {text[:80]!r}"


def test_new_cells_print_counts_from_the_run_not_from_a_literal():
    notebook = _load()
    new_code = "\n".join(c.source for c in notebook.cells[STARTER_CELLS:] if c.cell_type == "code")
    for name in ("BriefRuns", "evaluate_pair", "raw_summaries", "review_request"):
        assert name in new_code


# Running the notebook, when asked for.


@needs_run
def test_runner_names_the_cell_that_raises(tmp_path):
    notebook = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_code_cell("value = 1"),
            nbformat.v4.new_code_cell("raise ValueError('planted failure')"),
            nbformat.v4.new_code_cell("print('not reached')"),
        ]
    )
    with pytest.raises(NotebookCellError) as caught:
        execute_notebook(notebook, cwd=tmp_path)
    assert caught.value.index == 1
    assert caught.value.error_name == "ValueError"
    assert "planted failure" in str(caught.value)
    assert notebook.cells[2].outputs == []


@needs_run
def test_notebook_stops_by_name_when_a_recording_is_missing(tmp_path, monkeypatch):
    empty = tmp_path / "recordings"
    empty.mkdir()
    _replay_env(monkeypatch, empty)
    with pytest.raises(NotebookCellError) as caught:
        execute_notebook(_load(), cwd=NOTEBOOK.parent)
    assert caught.value.error_name == "ReplayMissError"
    assert "no recording" in str(caught.value)
    assert caught.value.index == 3


@needs_run
def test_notebook_runs_top_to_bottom_on_replay(monkeypatch):
    recordings = Path(
        os.environ.get("NOTEBOOK_RECORDINGS_DIR", str(TOPIC / "recordings"))
    ).resolve()
    _replay_env(monkeypatch, recordings)
    result = execute_notebook(_load(), cwd=NOTEBOOK.parent)

    modes = {mode for _, mode in result.call_log}
    assert modes == {"replay"}, f"a call was not served from a recording: {modes}"
    assert all((recordings / f"{key}.json").is_file() for key, _ in result.call_log)

    printed = "\n".join(
        _text_of(c) for c in result.notebook.cells[STARTER_CELLS:] if c.cell_type == "code"
    )
    for key in (
        "obligations_found",
        "invented_obligations",
        "quotes_word_for_word",
        "deadlines_as_written",
        "deadlines_matched",
        "paragraph_recall",
        "paragraph_precision",
    ):
        assert printed.count(key) >= 2, f"{key} is not shown for both the starter and our engine"
    assert "units accounted for" in printed

    committed = [_text_of(c) for c in _load().cells if c.cell_type == "code"]
    fresh = [_text_of(c) for c in result.notebook.cells if c.cell_type == "code"]
    drifted = [n for n, (old, new) in enumerate(zip(committed, fresh)) if old != new]
    assert not drifted, (
        f"the committed outputs of code cells {drifted} differ from a fresh replay run"
    )
