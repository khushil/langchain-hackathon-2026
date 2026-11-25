"""The shape of the three notebooks: the starter's cells kept, ours added after them, no secrets."""

from __future__ import annotations

import re

import nbformat
import pytest
from notebook_support import NAMES, STARTER_CELLS, code_of, load

ALLOWED_DIGIT_TOKENS = re.compile(r"USR-\d{3}|TX-\d{4}|[Ss]tep \d")
LIST_MARKER = re.compile(r"(?m)^\s*\d+\. ")


@pytest.mark.parametrize("name", NAMES)
def test_the_notebook_is_valid_nbformat_4_5(name):
    notebook = load(name)
    nbformat.validate(notebook)
    assert (notebook.nbformat, notebook.nbformat_minor) == (4, 5)
    assert len({c.id for c in notebook.cells}) == len(notebook.cells)


@pytest.mark.parametrize("name", NAMES)
def test_ours_are_added_after_the_starters_cells_and_none_before(name):
    notebook = load(name)
    starter = STARTER_CELLS[name]
    assert len(notebook.cells) > starter
    first_new = notebook.cells[starter]
    assert first_new.cell_type == "markdown"
    assert first_new.source.startswith("## What this notebook adds to the starter")


@pytest.mark.parametrize("name", NAMES)
def test_starter_cells_choose_their_model_through_get_model_only(name):
    cells = load(name).cells[: STARTER_CELLS[name]]
    code = "\n".join(c.source for c in cells if c.cell_type == "code")
    assert "init_chat_model" not in code
    assert "from utils.models import model" not in code


def test_the_agent_notebook_names_the_assessor_and_prints_the_graph_as_text():
    cells = load(NAMES[0]).cells
    assert 'get_model("assessor")' in cells[3].source
    assert 'model=get_model("assessor")' in cells[14].source
    assert "draw_mermaid()" in cells[18].source and "draw_mermaid_png" not in cells[18].source


def test_the_judge_runs_on_its_own_role():
    cells = load(NAMES[2]).cells
    assert 'get_model("judge")' in cells[14].source


@pytest.mark.parametrize(
    ("name", "indexes", "guard"),
    [
        (NAMES[1], (3, 11, 13), "langsmith_ready()"),
        (NAMES[2], (2,), "langsmith_ready()"),
        (NAMES[2], (6, 10, 12, 18), "client is None"),
    ],
)
def test_each_starter_step_that_talks_to_langsmith_is_guarded_and_says_so_in_one_sentence(
    name, indexes, guard
):
    cells = load(name).cells
    for index in indexes:
        source = cells[index].source
        assert guard in source, (name, index)
        assert "NEEDS_KEY" in source, (name, index)


def test_tracing_in_the_third_notebook_is_on_only_when_a_client_exists():
    source = load(NAMES[2]).cells[4].source
    assert "tracing_context(enabled=client is not None)" in source
    assert "enabled=True" not in source


@pytest.mark.parametrize("name", NAMES)
def test_the_notebook_builds_no_decision_and_no_sign_off(name):
    code = "\n".join(code_of(load(name)))
    for banned in ("Decision", "SignOff", "sign_off", ".submit("):
        assert banned not in code, (name, banned)


@pytest.mark.parametrize("name", NAMES)
def test_the_notebook_names_no_secret_and_sets_no_live_backend(name):
    code = "\n".join(code_of(load(name)))
    assert "LANGSMITH_KEY" not in code
    assert "MODEL_BACKEND" not in code
    assert "claude-code" not in code
    assert "enabled=True" not in code


@pytest.mark.parametrize("name", NAMES)
def test_new_markdown_types_no_number_that_a_run_could_change(name):
    notebook = load(name)
    new_markdown = [
        c.source for c in notebook.cells[STARTER_CELLS[name] :] if c.cell_type == "markdown"
    ]
    assert new_markdown
    for text in new_markdown:
        stripped = ALLOWED_DIGIT_TOKENS.sub("", LIST_MARKER.sub("", text))
        assert not re.search(r"\d", stripped), f"a number is typed in: {text[:80]!r}"


def test_new_cells_of_the_first_notebook_print_counts_from_the_run_not_from_a_literal():
    notebook = load(NAMES[0])
    new_code = "\n".join(
        c.source for c in notebook.cells[STARTER_CELLS[NAMES[0]] :] if c.cell_type == "code"
    )
    for name in ("MonitorRuns", "assessments_from_raw", "review_request", "UnitAccounting"):
        assert name in new_code


@pytest.mark.parametrize("name", NAMES)
def test_new_markdown_uses_no_dash_that_the_house_style_forbids(name):
    notebook = load(name)
    for cell in notebook.cells[STARTER_CELLS[name] :]:
        if cell.cell_type == "markdown":
            assert "—" not in cell.source and "–" not in cell.source
