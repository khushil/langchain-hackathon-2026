"""The assessing step: the starter's agent assesses each transaction of the window, in order.

The agent is the starter's, with its three tools, run on one conversation thread so that it
remembers the customer's earlier transactions. Its own pause for a person is switched off: here
the agent only proposes, and a named person decides at the review step. What it records for a
transaction is read from the starter's audit record and kept untouched in the state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from agent import build_agent
from context.checks import RecordedAssessment
from context.facts import assessment_fact
from fsi_common.ids import digest_text
from utils import PROJECT_ROOT
from utils.models import ROLE_MODELS
from utils.state import MyAgentContext
from utils.transaction_processing import transaction_message
from workflow.checks import run_check
from workflow.errors import AssessorPausedError
from workflow.intake import stream_of
from workflow.state import MonitorState

ModelSource = Callable[[str], BaseChatModel]
"""Gives the chat model for a role; ``get_model`` in production, a scripted fake in tests."""

INSTRUCTIONS = (PROJECT_ROOT / "instructions.md").read_text()
ASSESSOR_PROMPT_VERSION = f"assessor-{digest_text(INSTRUCTIONS)[7:15]}"
"""The prompt's version, taken from the digest of the starter's instructions."""

NEVER_ASK = float("-inf")
"""The confidence threshold that no confidence falls below, so the starter's tool never pauses."""


@dataclass(frozen=True)
class Recorded:
    """What the agent recorded for one transaction, and what it said at the end."""

    audit: dict[str, Any] | None
    reply: str

    def to_json(self) -> dict[str, Any]:
        """Return the record as the state keeps it."""
        return {"audit": self.audit, "reply": self.reply}


def assess_stream(
    models: ModelSource, state: MonitorState, today: Callable[[], str]
) -> dict[str, Any]:
    """Assess every transaction of the run's window with the starter's agent.

    Args:
        models: Gives the chat model for a role; ``assessor`` is asked for.
        state: The graph state, holding the request.
        today: Gives the date to record on each assessment, as ``YYYY-MM-DD``.

    Returns:
        The state update: each transaction's raw record, the facts that came from them and the
        count of what was recorded.

    Raises:
        AssessorPausedError: If the starter's tool paused to ask a person, which it is set never
            to do.
    """
    stream = stream_of(state)
    user_id = stream.user_id
    chat = models("assessor")
    agent = build_agent(model=chat, checkpointer=InMemorySaver(), store=InMemoryStore())
    config = {"configurable": {"thread_id": user_id}}
    context = MyAgentContext(user_id=user_id, confidence_threshold=NEVER_ASK)
    raw: dict[str, Any] = {}
    facts = {}
    observed_on = today()
    for row in stream.transactions:
        tx_id = row["transaction_id"]
        result = agent.invoke(transaction_message(tx_id), config, context=context)
        if "__interrupt__" in result:
            raise AssessorPausedError(
                f"The assessor's tool asked a person about {tx_id}; this workflow puts every "
                "transaction to the reviewer instead."
            )
        item = agent.store.get(("decisions", user_id), tx_id)
        recorded = Recorded(
            dict(item.value) if item is not None else None, result["messages"][-1].text
        )
        raw[tx_id] = recorded.to_json()
        if recorded.audit is not None:
            fact = assessment_fact(
                stream,
                row,
                RecordedAssessment.from_audit(recorded.audit),
                model=ROLE_MODELS["assessor"].model,
                prompt_version=ASSESSOR_PROMPT_VERSION,
                observed_on=observed_on,
            )
            facts[fact.id] = fact.to_json()
    window = {row["transaction_id"] for row in stream.transactions}
    stray = sorted(
        i.key for i in agent.store.search(("decisions", user_id), limit=1000) if i.key not in window
    )
    counts = sum(1 for r in raw.values() if r["audit"] is not None)
    detail = f"{counts} of {len(raw)} transactions of {user_id} have a recorded assessment"
    if stray:
        detail += f"; records for {', '.join(stray)}, which are not in the window, are not read"
    return {
        "raw_assessments": raw,
        "facts": facts,
        "check_results": run_check(
            "assessments-read.v1", stream.transaction_source.id, passed=True, detail=detail
        ),
    }


def make_assess_step(
    models: ModelSource, today: Callable[[], str]
) -> Callable[[MonitorState], dict[str, Any]]:
    """Build the assessing step over a source of models and a clock.

    Args:
        models: Gives the chat model for a role.
        today: Gives the date to record on each assessment.

    Returns:
        The graph node.
    """

    def assess(state: MonitorState) -> dict[str, Any]:
        return assess_stream(models, state, today)

    return assess
