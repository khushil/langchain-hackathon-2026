"""The brief: one statement for each assessment that passed its checks, written by code."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from context.reader import StreamRead
from fsi_common.records import Brief, Fact, OpenQuestion, Statement
from utils.models import ROLE_MODELS
from workflow.assess import ASSESSOR_PROMPT_VERSION
from workflow.closing import all_facts
from workflow.errors import NothingToReviewError
from workflow.intake import stream_of
from workflow.requests import request_of
from workflow.state import MonitorState

CONTEXT_FIELDS = ("home_country", "currency", "usual_amount_range")
"""The profile fields each statement cites beside the assessment: what the starter's checks read."""


def long_date(timestamp: str) -> str:
    """Write the date of a timestamp as "9 October 2026".

    Args:
        timestamp: A timestamp as the data writes it, for example ``2026-10-09T21:03``.

    Returns:
        The date in words.
    """
    day = datetime.fromisoformat(timestamp)
    return f"{day.day} {day.strftime('%B %Y')}"


def statement_text(fact: Fact) -> str:
    """Say what was proposed for a transaction, in words, from its assessment fact alone.

    Args:
        fact: An assessment fact.

    Returns:
        The transaction, what it was and what the assessor proposed with its reason.
    """
    a = fact.attributes
    tx_id = fact.subject.anchor.partition(":")[2]
    channel = str(a["channel"]).replace("_", " ")
    return (
        f"{tx_id} at {a['merchant']}, {a['amount']} {a['currency']} in {a['country']} "
        f"({channel}): proposed {a['proposed_decision']} at a risk score of {a['risk_score']} "
        f"and a confidence of {a['confidence']}. {a['reason']}"
    )


def write_brief(
    state: MonitorState, *, facts: list[Fact], questions: list[OpenQuestion], stream: StreamRead
) -> Brief:
    """Build the brief from the facts that passed, in the order of the transactions.

    Args:
        state: The graph state, for the request's words.
        facts: Every fact of the run.
        questions: The open questions of the run.
        stream: The stream, which gives the transactions' order.

    Returns:
        The brief, with a statement for each assessment that passed every check, each citing the
        assessment and the profile fields the starter's checks read.

    Raises:
        NothingToReviewError: If no assessment passed its checks.
    """
    assessments = {
        f.subject.anchor: f for f in facts if f.kind == "transaction_assessment" and f.passed_checks
    }
    profile = {
        f.attributes["field"]: f
        for f in facts
        if f.kind == "customer_attribute" and f.attributes["field"] in CONTEXT_FIELDS
    }
    statements = []
    for row in stream.transactions:
        fact = assessments.get(f"tx:{row['transaction_id']}")
        if fact is None:
            continue
        statements.append(
            Statement.build(
                heading=long_date(row["timestamp"]),
                text=statement_text(fact),
                cites=[fact.id, *(profile[name].id for name in CONTEXT_FIELDS)],
            )
        )
    if not statements:
        raise NothingToReviewError(
            f"No transaction of {stream.user_id} has an assessment that passed every check, so "
            "there is no brief to put to a reviewer."
        )
    return Brief.build(
        request=request_of(state)["request"],
        sources=[s.id for s in stream.sources],
        statements=statements,
        open_question_ids=sorted(q.id for q in questions),
        model=ROLE_MODELS["assessor"].model,
        prompt_version=ASSESSOR_PROMPT_VERSION,
    )


def write_brief_step(state: MonitorState) -> dict[str, Any]:
    """Write the brief the reviewer is put.

    Args:
        state: The graph state after the closing step.

    Returns:
        The state update holding the draft brief.

    Raises:
        NothingToReviewError: If no assessment passed its checks.
    """
    stream = stream_of(state)
    questions = [OpenQuestion.model_validate(q) for q in state.get("open_questions", {}).values()]
    brief = write_brief(state, facts=all_facts(state), questions=questions, stream=stream)
    return {"draft_brief": brief.to_json()}
