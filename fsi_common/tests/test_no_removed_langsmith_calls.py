"""A check that no code or notebook of the repository calls a removed LangSmith interface.

LangSmith removes the older run-reading and queue methods of its client, and the HTTP paths under
them, on 31 January 2027. The check reads every source file and every notebook of the repository
for those methods and for those paths. Sixteen of the methods are told apart by name alone. Two,
``list_runs`` and ``read_run``, are also the names of the application's own run registry, so they
are found on any receiver, through an alias, a method reference, ``getattr``, an async client or a
call split over lines (by reading the code as a syntax tree), and the registry's own uses are
allowed by name, in a short list below.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = Path(__file__).resolve()
SKIPPED_FOLDERS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "build",
    ".app-state",
    ".pytest_cache",
    ".ruff_cache",
}

NAMES_ONLY_THE_CLIENT_HAS = (
    "get_run_url",
    "list_threads",
    "read_thread",
    "share_run",
    "unshare_run",
    "read_run_shared_link",
    "run_is_shared",
    "list_shared_runs",
    "read_shared_run",
    "get_experiment_results",
    "add_runs_to_annotation_queue",
    "list_runs_from_annotation_queue",
    "get_run_from_annotation_queue",
    "delete_run_from_annotation_queue",
    "evaluate_run",
    "aevaluate_run",
)
"""Methods removed from the client. No code of ours has such a method, so any use counts."""

NAMES_THE_REGISTRY_SHARES = ("list_runs", "read_run")
"""Removed from the client, and also the names of the application's own run registry methods."""

CLIENT_RECEIVER = r"(?:\w*client\b|\bls\b|\bsmith\b|\bClient\([^)]*\))"
"""How a LangSmith client is usually named; it judges a ``getattr`` with a computed name."""

REGISTRY_RECEIVER = re.compile(r"^(?:\w+\.)*runs(?:\(\))?$|^runs_of\(\w+\)$")
"""The registry's receivers by name: ``runs``, ``self.runs``, ``services.runs()``, and so on."""

REGISTRY_RECEIVERS_BY_FILE = {
    "tests/workflow/test_workflow_durable.py": {"second"},
    "tests/review_app/test_seed.py": {"later"},
}
"""A receiver that is a registry in one test file only, named with the end of the file's path.

Each topic folder has its own copy of these files, so the end of the path is what is named.
"""

REGISTRY_STRINGS_BY_FILE = {
    "tests/review_app/review_fakes.py": {"list_runs"},
}
"""A string equal to a removed method's name that is the registry's, named the same way."""

REMOVED_PATHS = (
    r"/runs/query",
    r"/runs/group",
    r"/annotation-queues/status\b",
    r"/annotation-queues/[^\s\"']*/(?:runs|run/|size|total_size|total_archived)",
    r"/datasets/[^\s\"']*/runs\b",
    r"/runs/[^\s\"']*/share\b",
    r"/public/[^\s\"']*/(?:runs/query|run/)",
    r"/api/v1/runs/(?!multipart\b|batch\b)[^\s\"'?]+",
    r"/runs/\{[^}]*(?:run_?id|run_?uuid|trace_?id)[^}]*\}",
    r"/runs/(?:[\"']\s*[+%]|%s)",
)
"""The HTTP paths under the removed methods, with or without the version prefix.

The last three are the single-run read, ``GET /runs/{run_id}``, in the spellings it takes: with
the version prefix, with a placeholder named for a run id, and joined to the id by ``+`` or ``%``.
The application's own pages are ``/runs/{thread}``, which none of them matches.
"""

REMOVED_METHOD = re.compile(r"\b(" + "|".join(NAMES_ONLY_THE_CLIENT_HAS) + r")\b")
SHARED_NAME = re.compile(r"\.\s*(" + "|".join(NAMES_THE_REGISTRY_SHARES) + r")\b")
REMOVED_PATH = re.compile("|".join(REMOVED_PATHS))
CURRENT_PATH = re.compile(r"/api/v2/[^\s\"']*")
"""The paths of the interface that replaces the removed one; cut from a line before it is read."""


@dataclass(frozen=True)
class Finding:
    """One place that uses a removed method or path."""

    file: str
    line: int
    text: str


@dataclass(frozen=True)
class _Unit:
    """A piece of code and the line of the file where it starts."""

    text: str
    first_line: int


def _units(path: Path) -> tuple[str, list[_Unit]]:
    """The text a file is read as, and the code in it.

    A notebook is read as its code and markdown cells joined by lines; only its code cells are
    code. A source file is all code.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix != ".ipynb":
        return text, [_Unit(text, 1)]
    cells = json.loads(text).get("cells", [])
    sources = ["".join(cell.get("source", [])) for cell in cells]
    units, line = [], 1
    for cell, source in zip(cells, sources, strict=True):
        if cell.get("cell_type") == "code":
            units.append(_Unit(source, line))
        line += source.count("\n") + 1
    return "\n".join(sources), units


def _parse(unit: _Unit) -> ast.AST | None:
    """The syntax tree of a piece of code, or None when it is not whole Python."""
    magic_free = "\n".join(
        "pass" if line.lstrip().startswith(("%", "!")) else line for line in unit.text.split("\n")
    )
    try:
        return ast.parse(magic_free)
    except SyntaxError:
        return None


def _imports_langsmith(trees: list[ast.AST]) -> bool:
    """Whether any of the trees imports LangSmith, at the top or inside a function."""
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                a.name.split(".")[0] == "langsmith" for a in node.names
            ):
                return True
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == (
                "langsmith"
            ):
                return True
    return False


def _named_for(allowed: dict[str, set[str]], relative: str) -> set[str]:
    """What the allow lists name for a file, whichever topic folder the file is in."""
    return {
        name
        for ending, names in allowed.items()
        if relative == ending or relative.endswith("/" + ending)
        for name in names
    }


def _shared_names_in_tree(tree: ast.AST, *, relative: str, in_langsmith_file: bool) -> list[int]:
    """The lines of a tree that use ``list_runs`` or ``read_run`` other than as the registry does.

    In a file that imports LangSmith nothing is allowed: the registry's names count there too.
    """
    names = set(NAMES_THE_REGISTRY_SHARES)
    allowed_here = _named_for(REGISTRY_RECEIVERS_BY_FILE, relative)
    allowed_strings = _named_for(REGISTRY_STRINGS_BY_FILE, relative)
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in names:
            receiver = ast.unparse(node.value)
            is_registry = REGISTRY_RECEIVER.match(receiver) or receiver in allowed_here
            if in_langsmith_file or not is_registry:
                lines.append(node.end_lineno or node.lineno)
        elif isinstance(node, ast.Name) and node.id in names:
            if in_langsmith_file:
                lines.append(node.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in names and (in_langsmith_file or node.value not in allowed_strings):
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "langsmith":
            lines.extend(node.lineno for a in node.names if a.name in names)
        elif isinstance(node, ast.Call) and _is_computed_getattr(node):
            receiver = ast.unparse(node.args[0])
            if in_langsmith_file or re.search(CLIENT_RECEIVER, receiver):
                lines.append(node.lineno)
    return lines


def _is_computed_getattr(call: ast.Call) -> bool:
    """Whether a call is ``getattr`` with a name that is not written out as a string."""
    return (
        isinstance(call.func, ast.Name)
        and call.func.id == "getattr"
        and len(call.args) >= 2
        and not (isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str))
    )


def _shared_names_in_text(unit: _Unit, *, relative: str, in_langsmith_file: bool) -> list[int]:
    """The same, for code that does not parse, from its text: it fails closed."""
    allowed_here = _named_for(REGISTRY_RECEIVERS_BY_FILE, relative)
    lines: list[int] = []
    for offset, line in enumerate(unit.text.splitlines()):
        for found in SHARED_NAME.finditer(line):
            receiver = re.search(r"([\w.()]*)\s*$", line[: found.start()])
            name = receiver.group(1) if receiver else ""
            is_registry = REGISTRY_RECEIVER.match(name) or name in allowed_here
            if in_langsmith_file or not is_registry:
                lines.append(unit.first_line + offset)
        if re.search(r"getattr\(\s*" + CLIENT_RECEIVER + r"\s*,\s*[^\"'\s]", line):
            lines.append(unit.first_line + offset)
    return lines


def _lines_using_removed_calls(path: Path, relative: str) -> set[int]:
    """The 1-based lines of a file that use a removed method or path."""
    text, units = _units(path)
    trees = [_parse(unit) for unit in units]
    in_langsmith_file = _imports_langsmith([t for t in trees if t is not None]) or bool(
        re.search(r"\bimport langsmith\b|\bfrom langsmith\b", text)
    )
    hits: set[int] = set()
    for unit, tree in zip(units, trees, strict=True):
        if tree is None:
            found = _shared_names_in_text(
                unit, relative=relative, in_langsmith_file=in_langsmith_file
            )
        else:
            found = _shared_names_in_tree(
                tree, relative=relative, in_langsmith_file=in_langsmith_file
            )
        hits.update(unit.first_line - 1 + number for number in found)
    for number, line in enumerate(text.splitlines(), start=1):
        if REMOVED_METHOD.search(line) or REMOVED_PATH.search(CURRENT_PATH.sub("", line)):
            hits.add(number)
    return hits


def find_removed_calls(root: Path) -> list[Finding]:
    """Every use of a removed LangSmith method or path in the code and notebooks under a folder.

    Args:
        root: The folder to read.

    Returns:
        One finding for each line that uses one; empty when none does.
    """
    found: list[Finding] = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".py", ".ipynb"} or not path.is_file():
            continue
        if SKIPPED_FOLDERS & set(path.relative_to(root).parts) or path.resolve() == THIS_FILE:
            continue
        relative = path.relative_to(root).as_posix()
        text, _ = _units(path)
        lines = text.splitlines()
        for number in sorted(_lines_using_removed_calls(path, relative)):
            found.append(Finding(relative, number, lines[number - 1].strip()))
    return found


def test_no_code_or_notebook_of_the_repository_uses_a_removed_langsmith_interface():
    assert find_removed_calls(REPOSITORY_ROOT) == []


@pytest.mark.parametrize(
    "line",
    [
        "client.add_runs_to_annotation_queue(queue.id, run_ids=ids)",
        "queue = ls_client.list_runs_from_annotation_queue(queue_id)",
        "url = client.get_run_url(run=run)",
        "for run in client.list_runs(project_name=name):",
        "run = Client().read_run(run_id)",
        "run = self.client.read_run(run_id)",
        "feedback_client.list_runs(project_id=pid)",
        "await asyncio.to_thread(client.list_runs, project_name=name)",
        "runs = getattr(client, 'list_runs')(project_name=name)",
        "rows = functools.partial(ls.read_run, run_id)",
        "page = call('/api/v1/runs/query', body)",
        "page = call('/runs/query', body)",
        "page = call('/runs/group', body)",
        "post(f'{base}/annotation-queues/{queue}/runs', ids)",
        "post(f'{base}/api/v1/annotation-queues/{queue}/runs/by-key', keys)",
        "get(f'{base}/annotation-queues/{queue}/size')",
        "post(f'{base}/datasets/{dataset}/runs', body)",
        "put(f'{base}/runs/{run}/share')",
        "get(f'{base}/public/{token}/run/{run}')",
        "post(f'{base}/public/{token}/runs/query', {})",
        "client.share_run(run_id)",
        "client.get_experiment_results(name)",
        "client.list_threads(project_name=name)",
        "smith = Client(); smith.read_run(run_id)",
        "run = smith.read_run(run_id)",
        "rows = c.list_runs(project_name=name)",
        "rows = map(Client.list_runs, names)",
        "run = await AsyncClient().read_run(run_id)",
        "rows = Client(api_key=os.getenv('K')).list_runs(project_name=name)",
        "rows = langsmith.Client().list_runs(project_name=name)",
        "    .list_runs(project_name=name)",
        "method = getattr(client, name)",
        "get(f'{base}/api/v1/runs/{run_id}')",
        "get(f'{base}/runs/{run_id}')",
        "post(f'{base}/api/v1/annotation-queues/status/{queue_run_id}', body)",
        "method = getattr(client, 'list_' + 'runs')",
        "rows = operator.methodcaller('list_runs', project_name=name)(c)",
        "ok = hasattr(smith, 'read_run')",
        "from langsmith import read_run",
        "get(base + '/runs/' + run_id)",
        "get('/runs/%s' % run_id)",
        "get('/api/v1/runs/' + run_id)",
        "get('/annotation-queues/status/' + queue_id)",
    ],
)
@pytest.mark.parametrize("kind", ["py", "ipynb"])
def test_a_planted_removed_call_is_found(tmp_path, kind, line):
    if kind == "py":
        (tmp_path / "planted.py").write_text(f"x = 1\n{line}\n", encoding="utf-8")
    else:
        cell = {"cell_type": "code", "source": ["x = 1\n", line + "\n"]}
        (tmp_path / "planted.ipynb").write_text(json.dumps({"cells": [cell]}), encoding="utf-8")
    [found] = find_removed_calls(tmp_path)
    assert found.line == 2 and found.text == line.strip()


@pytest.mark.parametrize(
    "line",
    [
        "runs.list_runs()",
        "self.runs.list_runs()",
        "info = runs_of(services).list_runs()",
        "first = services.runs().list_runs()",
        "assert served.runs.list_runs() == []",
        "value = getattr(real, name)",
        "order = runs.list_runs()  # newest first",
        "info = read_run(services, thread_id)",
        "def read_run(services: Services, thread_id: str) -> RunInfo:",
        "def list_runs(self) -> list[str]: ...",
        "client = Client(api_key=key)",
        "client.create_feedback(run_id, key, session_id=pid)",
        "client.list_annotation_queues(name=QUEUE_NAME)",
        "await client.annotation_queues.items.create(queue_id, items=items)",
        "page = await client.runs.query(project_ids=[pid], min_start_time=start)",
        "client.read_project(project_name=name)",
        "Route('/runs/{thread}/review', review_get)",
        "action = '/compliance-brief/runs/{thread}/sign'",
        "call('/api/v2/runs/query', body)",
        "post(f'{base}/api/v1/runs/batch', body)",
        "post(f'{base}/api/v1/runs/multipart', body)",
        "Route('/runs/{run}', second)",
        "page = client.get(f'{PREFIX}/runs/{thread}/facts')",
        "post(f'{base}/api/v1/platform/annotation-queues/{queue}/items', body)",
    ],
)
def test_the_applications_own_run_registry_and_the_current_calls_are_not_found(tmp_path, line):
    (tmp_path / "fine.py").write_text(f"x = 1\n{line}\n", encoding="utf-8")
    assert find_removed_calls(tmp_path) == []


def test_a_folder_that_is_skipped_is_not_read(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("client.list_runs()\n", encoding="utf-8")
    assert find_removed_calls(tmp_path) == []


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    ("code", "line"),
    [
        ("rows = (\n    smith\n    .list_runs(project_name=name)\n)\n", 3),
        ("run = (\n    Client(\n        api_key=key,\n    ).read_run(run_id)\n)\n", 4),
        ("method = smith.list_runs\nrows = method(project_name=name)\n", 1),
        ("import functools\nrows = functools.partial(\n    smith.read_run,\n    run_id)\n", 3),
        (
            "from langsmith import AsyncClient\nasync def f():\n    return await AsyncClient()\\\n"
            "        .read_run(run_id)\n",
            4,
        ),
    ],
)
def test_a_call_in_whole_python_is_found_on_the_line_of_its_name(tmp_path, code, line):
    _write(tmp_path, "planted.py", code)
    [found] = find_removed_calls(tmp_path)
    assert found.line == line


def test_a_registry_receiver_is_not_allowed_in_a_file_that_imports_langsmith(tmp_path):
    _write(tmp_path, "mixed.py", "import langsmith\nruns = langsmith.Client()\nruns.list_runs()\n")
    [found] = find_removed_calls(tmp_path)
    assert (found.file, found.line) == ("mixed.py", 3)


def test_a_bare_name_is_allowed_outside_a_file_that_imports_langsmith_and_not_in_one(tmp_path):
    _write(tmp_path, "app.py", "info = read_run(services, thread)\n")
    assert find_removed_calls(tmp_path) == []
    _write(tmp_path, "client.py", "from langsmith import Client\nrun = read_run(services, 1)\n")
    [found] = find_removed_calls(tmp_path)
    assert (found.file, found.line) == ("client.py", 2)


def test_a_receiver_that_is_a_registry_in_one_file_is_a_registry_only_there(tmp_path):
    for named in (
        "03_document_summary_agent/tests/workflow/test_workflow_durable.py",
        "01_kyc_agent/tests/workflow/test_workflow_durable.py",
    ):
        _write(tmp_path, named, "assert second.list_runs() == [thread_id]\n")
    _write(tmp_path, "02_x/tests/review_app/test_seed.py", "assert len(later.list_runs()) == 2\n")
    assert find_removed_calls(tmp_path) == []
    _write(tmp_path, "other.py", "assert second.list_runs() == [thread_id]\n")
    [found] = find_removed_calls(tmp_path)
    assert found.file == "other.py"


def test_the_registry_string_is_allowed_in_the_fake_that_names_it_and_nowhere_else(tmp_path):
    named = "03_document_summary_agent/tests/review_app/review_fakes.py"
    _write(tmp_path, named, 'self._note("list_runs")\n')
    assert find_removed_calls(tmp_path) == []
    _write(tmp_path, "other.py", 'self._note("list_runs")\n')
    [found] = find_removed_calls(tmp_path)
    assert found.file == "other.py"


def test_a_getattr_with_a_computed_name_on_a_client_is_found_and_on_anything_else_is_not(tmp_path):
    _write(
        tmp_path, "a.py", "value = getattr(real, name)\nmethod = getattr(feedback_client, name)\n"
    )
    [found] = find_removed_calls(tmp_path)
    assert found.line == 2


def test_a_notebook_code_cell_is_read_as_code_and_a_markdown_cell_is_not(tmp_path):
    cells = [
        {"cell_type": "markdown", "source": ["Use runs.list_runs() or smith.read_run here.\n"]},
        {"cell_type": "code", "source": ["%matplotlib inline\n", "rows = smith.list_runs()\n"]},
    ]
    (tmp_path / "n.ipynb").write_text(json.dumps({"cells": cells}), encoding="utf-8")
    [found] = find_removed_calls(tmp_path)
    assert found.text == "rows = smith.list_runs()" and found.line == 4
