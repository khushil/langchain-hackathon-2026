"""Every code cell of the notebook runs, in order, on scripted models, in this process.

The recorded run does not exist until the lead records it, so this proves each cell runs and
prints what it should on a scripted reader; the replay test in ``test_notebook_runs`` proves the
same on the recordings. No model is called: the adapter's chat model is replaced for the test.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
from typing import Any

import nbformat
import pytest
from kyc_fakes import ScriptedReader, reading_of
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from context.extraction import ApplicantRead
from utils import db
from utils.models import DeferredChatModel

NOTEBOOK = Path(__file__).resolve().parents[2] / "modules" / "01_kyc_agent.ipynb"


class NotebookFake(BaseChatModel):
    """A chat model that reads the 25 applications as the scripted reader does and writes a memo."""

    @property
    def _llm_type(self) -> str:
        return "notebook-fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Memo."))])

    def with_structured_output(self, schema: Any, **kwargs: Any):
        if schema is ApplicantRead:
            return ScriptedReader()("extract").with_structured_output(schema)

        def read(prompt: Any):
            text = prompt if isinstance(prompt, str) else str(prompt)
            row = next(r for r in db.table("applications") if r["application"] in text)
            reading = reading_of(row["customer_id"])
            return schema(
                full_name=reading.full_name.value,
                date_of_birth=reading.date_of_birth.value,
                nationality="n",
                occupation="o",
                source_of_funds="s",
            )

        return RunnableLambda(read)


@pytest.fixture()
def scripted_models(monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "replay")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setattr(DeferredChatModel, "resolve", lambda self: NotebookFake())
    monkeypatch.chdir(NOTEBOOK.parent)


def run_cells(upto: int | None = None) -> dict[int, str]:
    """Run the notebook's code cells in order in one namespace; return what each printed."""
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    namespace: dict[str, Any] = {"__name__": "__main__"}
    printed: dict[int, str] = {}
    for index, cell in enumerate(notebook.cells[:upto]):
        if cell.cell_type != "code":
            continue
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exec(compile(cell.source, f"<cell {index}>", "exec"), namespace)  # noqa: S102
        printed[index] = out.getvalue()
    return printed


@pytest.fixture()
def printed(scripted_models):
    return run_cells()


def test_every_code_cell_runs_and_the_starters_cells_print_what_the_starter_says(printed):
    assert "Say hello" not in printed[4] and printed[4].strip()
    assert "Watchlists: 8 sanctioned people, 6 PEPs" in printed[7]
    assert "Dmitri Volkonsky" in printed[9]
    assert "high" in printed[19] and "Next node: human_review" in printed[19]
    assert "Risk: low  Decision: approve (by system)" in printed[27]
    assert "Paused at: ('human_review',)" in printed[29]
    assert "Decision: reject (by human)" in printed[31]
    assert len([line for line in printed[33].splitlines() if line.startswith("CUST-")]) == 25
    assert "flowchart" in printed[25].lower() or "graph" in printed[25].lower()


def test_the_run_accounts_for_every_application_and_every_pairing(printed):
    text = "\n".join(printed.values())
    assert "applications: 25 of 25 units accounted for, 25 with facts and 0 with none" in text
    assert "screenings: 350 of 350 units accounted for" in text
    assert "No likeness" in text


def test_the_checks_settle_some_and_a_person_gets_the_rest(printed):
    text = "\n".join(printed.values())
    assert "13 of 25 applications settled by the checks; 12 sent to a person" in text


def test_the_three_edge_cases_are_taken_from_the_labels_and_each_asks_a_question(printed):
    text = "\n".join(printed.values())
    assert "3 edge cases in the starter's labels" in text
    for customer_id in ("CUST-015", "CUST-018", "CUST-021"):
        assert f"{customer_id}  starter's label:" in text
    assert text.count("The same person:") >= 3 and text.count("A different person:") >= 3


def test_the_measures_are_printed_with_the_starters_rule_beside_the_engine(printed):
    text = "\n".join(printed.values())
    assert "risk_agrees: 23 of 25 applications" in text
    assert "starter_risk_agrees: 22 of 25 applications" in text
    assert "edge_cases_sent: 3 of 3" in text
    assert "this engine 23 of 25" in text and "starter's rule 22 of 25" in text


def test_the_run_decides_nothing_and_the_reviewer_is_shown_every_proposal(printed):
    text = "\n".join(printed.values())
    assert "Statements for the reviewer: 25" in text
    assert "Decisions recorded by this run: 0" in text
    assert "Signed off: False" in text


def test_a_model_that_fails_stops_the_run_of_cells_at_the_first_call(scripted_models, monkeypatch):
    def refuse(self):
        raise RuntimeError("planted: no model")

    monkeypatch.setattr(DeferredChatModel, "resolve", refuse)
    with pytest.raises(RuntimeError, match="planted: no model"):
        run_cells()


def test_a_run_that_fails_before_the_review_is_named_by_the_wait_cell(scripted_models, monkeypatch):
    original = NotebookFake.with_structured_output

    def refuse_the_engines_reading(self, schema, **kwargs):
        if schema is ApplicantRead:
            raise RuntimeError("planted: the reading failed")
        return original(self, schema, **kwargs)

    monkeypatch.setattr(NotebookFake, "with_structured_output", refuse_the_engines_reading)
    with pytest.raises(Exception, match="the reading failed") as caught:
        run_cells()
    assert type(caught.value).__name__ == "RunDidNotReachReviewError"
