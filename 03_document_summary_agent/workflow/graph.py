"""The compliance brief graph: read, fan out the sections, close the counts, write, review."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from utils.models import get_model
from utils.state import BriefInput
from workflow.briefing import make_brief_step
from workflow.closing import close_run
from workflow.engine_state import EngineState, SectionTask
from workflow.intake import read_sources, send_sections
from workflow.review import make_review_step
from workflow.sections import ModelSource, make_section_step

GRAPH_NAME = "compliance-brief"
NODES = ("read_sources", "section", "close_run", "write_brief", "review")
"""The graph's nodes in order; ``section`` runs once for each section selected."""


def route_after_review(state: EngineState) -> str:
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
) -> Any:
    """Compile the compliance brief graph.

    Args:
        models: Gives the chat model for a role (``section`` and ``brief`` are asked for).
        checkpointer: Keeps the run, and the review interrupt, between calls.
        store: Holds the decisions of earlier runs.

    Returns:
        The compiled graph, named ``compliance-brief``.
    """
    builder = StateGraph(EngineState, input_schema=BriefInput)
    builder.add_node("read_sources", read_sources)
    builder.add_node("section", make_section_step(models), input_schema=SectionTask)
    builder.add_node("close_run", close_run)
    builder.add_node("write_brief", make_brief_step(models))
    builder.add_node("review", make_review_step())
    builder.add_edge(START, "read_sources")
    builder.add_conditional_edges("read_sources", send_sections, ["section"])
    builder.add_edge("section", "close_run")
    builder.add_edge("close_run", "write_brief")
    builder.add_edge("write_brief", "review")
    builder.add_conditional_edges("review", route_after_review, ["review", END])
    return builder.compile(checkpointer=checkpointer, store=store, name=GRAPH_NAME)


graph = build_graph()
"""The graph as ``langgraph.json`` registers it; the platform supplies its own checkpointer."""
