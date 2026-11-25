"""The KYC onboarding graph: read, screen, close the counts, write, review."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from utils.kyc_state import KycInput
from utils.models import get_model
from workflow.briefing import write_brief
from workflow.closing import close_run
from workflow.engine_state import EngineState, ReadTask
from workflow.intake import read_sources, send_applications
from workflow.reading import ModelSource, make_read_step
from workflow.review import make_review_step
from workflow.screening import screen_and_propose

GRAPH_NAME = "kyc-onboarding"
NODES = ("read_sources", "read_application", "screen", "close_run", "write_brief", "review")
"""The graph's nodes in order; ``read_application`` runs once for each application."""


def route_after_review(state: EngineState) -> str:
    """Send the run on to its end once the reviewer has signed or returned the batch.

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
    """Compile the KYC onboarding graph.

    Args:
        models: Gives the chat model for a role (``extract`` is asked for).
        checkpointer: Keeps the run, and the review interrupt, between calls.
        store: Holds the decisions of earlier runs.

    Returns:
        The compiled graph, named ``kyc-onboarding``.
    """
    builder = StateGraph(EngineState, input_schema=KycInput)
    builder.add_node("read_sources", read_sources)
    builder.add_node("read_application", make_read_step(models), input_schema=ReadTask)
    builder.add_node("screen", screen_and_propose)
    builder.add_node("close_run", close_run)
    builder.add_node("write_brief", write_brief)
    builder.add_node("review", make_review_step())
    builder.add_edge(START, "read_sources")
    builder.add_conditional_edges("read_sources", send_applications, ["read_application"])
    builder.add_edge("read_application", "screen")
    builder.add_edge("screen", "close_run")
    builder.add_edge("close_run", "write_brief")
    builder.add_edge("write_brief", "review")
    builder.add_conditional_edges("review", route_after_review, ["review", END])
    return builder.compile(checkpointer=checkpointer, store=store, name=GRAPH_NAME)


graph = build_graph()
"""The graph as ``langgraph.json`` registers it; the platform supplies its own checkpointer."""
