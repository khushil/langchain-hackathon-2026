"""The transaction monitoring graph: read, assess, close the counts, write, review."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from utils.models import get_model
from workflow.assess import ModelSource, make_assess_step
from workflow.briefing import write_brief_step
from workflow.closing import close_run
from workflow.intake import read_sources
from workflow.review import make_review_step
from workflow.state import MonitorInput, MonitorState

GRAPH_NAME = "transaction-monitoring"
NODES = ("read_sources", "assess", "close_run", "write_brief", "review")
"""The graph's nodes in order."""


def today_iso() -> str:
    """Return today's date as ``YYYY-MM-DD``."""
    return date.today().isoformat()


def route_after_review(state: MonitorState) -> str:
    """Send the run on to its end once the reviewer has signed or returned the brief.

    Args:
        state: The graph state.

    Returns:
        ``review`` again while no sign-off has been received, and the end otherwise.
    """
    return END if state.get("sign_off") else "review"


def build_graph(
    *,
    models: ModelSource = get_model,
    checkpointer: BaseCheckpointSaver | None = None,
    store: BaseStore | None = None,
    today: Callable[[], str] = today_iso,
) -> Any:
    """Compile the transaction monitoring graph.

    Args:
        models: Gives the chat model for a role (``assessor`` is asked for).
        checkpointer: Keeps the run, and the review interrupt, between calls.
        store: Holds the decisions of earlier runs.
        today: Gives the date to record on each assessment.

    Returns:
        The compiled graph, named ``transaction-monitoring``.
    """
    builder = StateGraph(MonitorState, input_schema=MonitorInput)
    builder.add_node("read_sources", read_sources)
    builder.add_node("assess", make_assess_step(models, today))
    builder.add_node("close_run", close_run)
    builder.add_node("write_brief", write_brief_step)
    builder.add_node("review", make_review_step())
    builder.add_edge(START, "read_sources")
    builder.add_edge("read_sources", "assess")
    builder.add_edge("assess", "close_run")
    builder.add_edge("close_run", "write_brief")
    builder.add_edge("write_brief", "review")
    builder.add_conditional_edges("review", route_after_review, ["review", END])
    return builder.compile(checkpointer=checkpointer, store=store, name=GRAPH_NAME)


graph = build_graph()
"""The graph as ``langgraph.json`` registers it; the platform supplies its own checkpointer."""
