"""Running a notebook top to bottom in a kernel, and reading what its cells printed."""

from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

TOPIC = Path(__file__).resolve().parents[2]
REPO = TOPIC.parent
MODULES = TOPIC / "modules"
NAMES = (
    "01_transaction_monitoring_agent.ipynb",
    "02_scoring_evals.ipynb",
    "03_annotation_queue.ipynb",
)
STARTER_CELLS = {NAMES[0]: 42, NAMES[1]: 15, NAMES[2]: 20}
CELL_TIMEOUT_S = 900
FAKE = Path(__file__).with_name("fake_claude.py")
DATA_LINE = 'DATA = str(Path(__file__).resolve().parents[2] / "data")'

CALL_LOG_CELL = """
import json
try:
    from fsi_common.model import call_records
    log = [[r.request_hash, r.mode] for r in call_records()]
except ImportError:
    log = []
print("CALL_LOG " + json.dumps(log))
"""


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
    """The model calls the kernel made, each as (request hash, mode)."""


def load(name: str) -> nbformat.NotebookNode:
    """Read one of the topic's notebooks."""
    return nbformat.read(MODULES / name, as_version=4)


def code_of(notebook: nbformat.NotebookNode) -> list[str]:
    """Return the source of every code cell."""
    return [c.source for c in notebook.cells if c.cell_type == "code"]


def text_of(cell: nbformat.NotebookNode) -> str:
    """Return the text a code cell printed or returned."""
    parts = []
    for output in cell.get("outputs", []):
        if output.output_type == "stream":
            parts.append(output.text)
        elif output.output_type in ("execute_result", "display_data"):
            parts.append(output.data.get("text/plain", ""))
    return "".join(parts)


def _first_line(source: str) -> str:
    lines = source.strip().splitlines()
    return lines[0][:70] if lines else ""


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
    marker = next(line for line in text_of(log_cell).splitlines() if line.startswith("CALL_LOG "))
    return RunResult(notebook, [tuple(pair) for pair in json.loads(marker[len("CALL_LOG ") :])])


def stand_in_for_claude(folder: Path) -> Path:
    """Write an executable ``claude`` into a folder, which answers from a script and runs no model.

    Args:
        folder: Where to put it; it is made if absent.

    Returns:
        The folder, to put first on ``PATH``.
    """
    folder.mkdir(parents=True, exist_ok=True)
    text = FAKE.read_text(encoding="utf-8").replace(DATA_LINE, f"DATA = {str(TOPIC / 'data')!r}")
    program = folder / "claude"
    program.write_text(f"#!{sys.executable}\n{text}", encoding="utf-8")
    program.chmod(program.stat().st_mode | stat.S_IEXEC)
    return folder


def kernel_env(monkeypatch, *, backend: str, recordings: Path, bin_dir: Path | None = None) -> None:
    """Point the next kernel at a backend and a recordings folder, with no tracing and no key."""
    monkeypatch.setenv("MODEL_BACKEND", backend)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("MODEL_RECORDINGS_DIR", str(recordings))
    for name in ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_KEY"):
        monkeypatch.delenv(name, raising=False)
    path = [str(REPO / "fsi_common"), os.environ.get("PYTHONPATH", "")]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(part for part in path if part))
    if bin_dir is not None:
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
