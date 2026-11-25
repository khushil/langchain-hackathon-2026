"""A compiled graph on the scripted reader, and the answers a named person gives, for the tests."""

from __future__ import annotations

from typing import Any

from kyc_fakes import ScriptedReader

from fsi_common.records import Decision, SignOff
from utils.kyc_state import ReviewRequest, ReviewResponse

REVIEWER = {"name": "Dana Whitfield", "role": "Head of Compliance"}
REVIEW_DATE = "2026-11-25"


def respond(
    request: ReviewRequest,
    *,
    outcome: str = "signed",
    reviewer: dict[str, str] = REVIEWER,
    decide: str | None = "accept",
    answer: str = "The same person.",
    reason: str = "Returned for another look.",
    assume: bool = False,
) -> ReviewResponse:
    """Answer a review request as a named person would.

    Each proposal fact is decided as ``decide`` says, each open question is answered, and the
    batch is signed or returned. Facts that carry an earlier decision are left as they are.
    """
    decisions = []
    if decide:
        for statement in request.statements:
            for cited in statement.facts:
                if cited.fact.kind == "proposal" and cited.carry.outcome != "carried":
                    decisions.append(
                        Decision.on(
                            cited.fact,
                            outcome=decide,
                            reason="Checked against the application and the lists.",
                            reviewer=reviewer,
                            date=REVIEW_DATE,
                            amendment="Low risk, approve." if decide == "amend" else None,
                        )
                    )
    assumptions = []
    for question in request.open_questions:
        if question.state in {"answered", "accepted", "closed_no_answer"}:
            continue
        if assume:
            assumptions.append(
                {"question_id": question.id, "words": "Assume the cautious reading."}
            )
        else:
            decisions.append(
                Decision.on(
                    question,
                    outcome="answer",
                    answer=answer,
                    reason="Read the application and the entry.",
                    reviewer=reviewer,
                    date=REVIEW_DATE,
                )
            )
    sign_off = SignOff.build(
        brief_id=request.brief_id,
        brief_digest=request.brief_digest,
        reviewer=reviewer,
        date=REVIEW_DATE,
        outcome=outcome,
        assumptions=assumptions,
        reason=reason if outcome == "returned" else None,
    )
    return ReviewResponse(reviewer=reviewer, decisions=decisions, sign_off=sign_off)


def kyc_request(*customers: str) -> dict[str, Any]:
    """Return a run's input, filtered to customers when any are named."""
    request: dict[str, Any] = {"request": "Review the proposed decisions on the applications"}
    if customers:
        request["customer_ids"] = list(customers)
    return {"request": request}


def bundle_records(values: dict[str, Any]) -> list[Any]:
    """Return a run's state as the records the contract's bundle check reads."""
    from fsi_common.records import RECORD_TYPES, Fact
    from utils.records import FACT_CONTEXT

    records = []
    for key in ("sources", "units", "accounting", "open_questions", "disagreements", "decisions"):
        for data in values.get(key, {}).values():
            records.append(RECORD_TYPES[data["schema"]].model_validate(data, context=FACT_CONTEXT))
    for contents in values["facts"].values():
        for data in contents:
            records.append(Fact.model_validate(data, context=FACT_CONTEXT))
    for key in ("draft_brief", "sign_off"):
        if values.get(key):
            records.append(RECORD_TYPES[values[key]["schema"]].model_validate(values[key]))
    return records


class Harness:
    """A compiled graph with its own checkpointer and store, and the calls a test makes on it."""

    def __init__(self, models: ScriptedReader | None = None, *, store: Any = None) -> None:
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore

        from workflow.graph import build_graph

        self.models = models or ScriptedReader()
        self.store = store or InMemoryStore()
        self.graph = build_graph(models=self.models, checkpointer=InMemorySaver(), store=self.store)
        self.count = 0

    def start(self, *customers: str, thread: str | None = None) -> dict[str, Any]:
        """Run to the review interrupt, and return the thread's configuration."""
        self.count += 1
        config = {
            "configurable": {"thread_id": thread or f"thread-{self.count}"},
            "max_concurrency": 4,
        }
        self.graph.invoke(kyc_request(*customers), config)
        return config

    def values(self, config: dict[str, Any]) -> dict[str, Any]:
        """Return the thread's state as it stands."""
        return self.graph.get_state(config).values

    def review_request(self, config: dict[str, Any]) -> ReviewRequest:
        """Return the payload the review interrupt holds."""
        from utils.records import FACT_CONTEXT

        task = self.graph.get_state(config).tasks[0]
        return ReviewRequest.model_validate(task.interrupts[0].value, context=FACT_CONTEXT)

    def resume(self, config: dict[str, Any], response: ReviewResponse) -> dict[str, Any]:
        """Resume the review with a response, and return the graph's output."""
        from langgraph.types import Command

        return self.graph.invoke(
            Command(resume=response.model_dump(mode="json", by_alias=True)), config
        )
