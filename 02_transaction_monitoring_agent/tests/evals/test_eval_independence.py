"""The evaluators must not depend on the system they score, and must not call a model."""

import ast
from pathlib import Path

import pytest

EVALS = Path(__file__).resolve().parents[2] / "evals"
SCORING = ["evaluators.py", "reference_assessments.py", "planted_faults.py"]
FORBIDDEN = {
    "workflow",
    "context",
    "agent",
    "agents",
    "deepagents",
    "langchain",
    "langchain_core",
    "langchain_anthropic",
    "langchain_openai",
    "langgraph",
    "anthropic",
    "openai",
    "subprocess",
    "requests",
    "httpx",
}


def imported_modules(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("name", SCORING)
def test_scoring_modules_import_nothing_from_the_engine_or_a_model_library(name):
    modules = imported_modules(EVALS / name)
    roots = {m.split(".")[0] for m in modules}
    assert roots.isdisjoint(FORBIDDEN), roots & FORBIDDEN
    assert not any(m.startswith(("utils", "fsi_common.model")) for m in modules)


def test_the_scan_catches_a_forbidden_import(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("from workflow.graph import graph\nimport utils.models\n", encoding="utf-8")
    roots = {m.split(".")[0] for m in imported_modules(bad)}
    assert roots & FORBIDDEN == {"workflow"}
    assert "utils.models" in imported_modules(bad)
