"""The application and the notebook ask with one request text, so one recorded run answers both."""

import ast
import json
from pathlib import Path

from workflow.requests import brief_request_text

TOPIC = Path(__file__).resolve().parents[2]
STARTER_CELLS = 23


def test_brief_request_text_is_the_starters_wording():
    assert brief_request_text("PS26-4", "FIRM-001") == "Summarise document PS26-4 for FIRM-001"


def test_the_application_and_the_notebook_build_the_request_with_the_one_function():
    start = (TOPIC / "review_app" / "routes_start.py").read_text(encoding="utf-8")
    calls = [
        node.func.id
        for node in ast.walk(ast.parse(start))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "brief_request_text" in calls
    strings = [
        node.value
        for node in ast.walk(ast.parse(start))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert not [text for text in strings if text.startswith("Summarise document")]
    notebook = json.loads((TOPIC / "modules" / "01_document_summary_agent.ipynb").read_text())
    ours = notebook["cells"][STARTER_CELLS:]
    code = "\n".join("".join(c["source"]) for c in ours if c["cell_type"] == "code")
    assert "brief_request_text(" in code
    assert "Summarise document" not in code
