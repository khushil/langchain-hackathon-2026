"""Scripted models and review responses for the workflow's tests; no test makes a live call."""

from __future__ import annotations

import threading
from typing import Any

from model_fakes import Assessment, ScriptedAssessor, assessment_for_score

from fsi_common.records import RECORD_TYPES, Brief, Decision, SignOff
from utils import db
from utils.records import FACT_CONTEXT
from utils.review import ReviewRequest, ReviewResponse

DANA = {"name": "Dana Whitfield", "role": "Head of Compliance"}
REVIEW_DATE = "2026-11-25"


def label_script() -> dict[str, Assessment]:
    """Script every transaction of the starter's data at the analysts' score for it.

    The eleven labelled transactions take the analysts' scores, and the four of the later week the
    scores the simulated reviewers gave; the decision follows the starter's rule.
    """
    scores = {row["transaction_id"]: row["risk_score"] for row in db.table("analyst_labels")}
    scores |= {
        row["transaction_id"]: row["correct_risk_score"]
        for row in db.table("simulated_annotations")
    }
    return {tx: assessment_for_score(score) for tx, score in scores.items()}


class ScriptedModels:
    """Gives the scripted assessor for the ``assessor`` role, and keeps the transactions it saw."""

    def __init__(
        self,
        script: dict[str, Assessment | None] | None = None,
        *,
        hold: threading.Event | None = None,
        fail: tuple[str, ...] = (),
    ) -> None:
        self.script = label_script() if script is None else script
        self.hold, self.fail = hold, fail
        self.calls: list[str] = []
        self.roles: list[str] = []

    def visit(self, tx: str) -> None:
        """Note that the assessor began a transaction, wait for the gate, and fail when told to."""
        self.calls.append(tx)
        if self.hold is not None:
            self.hold.wait(10)
        if tx in self.fail:
            raise RuntimeError(f"the model call for {tx} failed")

    def __call__(self, role: str):
        self.roles.append(role)
        if role != "assessor":
            raise AssertionError(f"the workflow asked for the model of role {role!r}")
        return ScriptedAssessor(script=self.script, calls=[], owner=self)


def request_for(user: str = "USR-001", **window: str) -> dict[str, Any]:
    """Return a run's input for one customer, with a window when given as start and end."""
    return {"request": {"user_id": user, "request": f"Assess the transactions of {user}", **window}}


def respond(
    request: ReviewRequest,
    *,
    outcome: str = "signed",
    reviewer: dict[str, str] = DANA,
    decide: str | None = "accept",
    reason: str = "Returned for a rewrite.",
    answer_questions: bool = True,
) -> ReviewResponse:
    """Answer a review request as a named person would: decide on each assessment, then sign it."""
    decisions = []
    if decide:
        for cited in request.assessments:
            if cited.carry.outcome != "carried":
                decisions.append(
                    Decision.on(
                        cited.fact,
                        outcome=decide,
                        reason="Checked against what the customer told us.",
                        reviewer=reviewer,
                        date=REVIEW_DATE,
                        amendment="Block it." if decide == "amend" else None,
                    )
                )
    if answer_questions:
        for question in request.open_questions:
            if question.state not in {"answered", "accepted", "closed_no_answer"}:
                decisions.append(
                    Decision.on(
                        question,
                        outcome="answer",
                        answer="Approve it.",
                        reason="Called the customer.",
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
        assumptions=[],
        reason=reason if outcome == "returned" else None,
    )
    return ReviewResponse(reviewer=reviewer, decisions=decisions, sign_off=sign_off)


class Harness:
    """A compiled graph with its own checkpointer and store, and the calls a test makes on it."""

    def __init__(self, models: ScriptedModels | None = None, *, store: Any = None) -> None:
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore

        from workflow.graph import build_graph

        self.models = models or ScriptedModels()
        self.store = store or InMemoryStore()
        self.graph = build_graph(
            models=self.models,
            checkpointer=InMemorySaver(),
            store=self.store,
            today=lambda: REVIEW_DATE,
        )
        self.count = 0

    def start(self, user: str = "USR-001", *, thread: str | None = None, **window: str) -> dict:
        """Run to the review interrupt, and return the thread's configuration."""
        self.count += 1
        config = {
            "configurable": {"thread_id": thread or f"thread-{self.count}"},
            "max_concurrency": 4,
        }
        self.graph.invoke(request_for(user, **window), config)
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


def bundle_of(values: dict[str, Any]) -> list[Any]:
    """Return a run's state as the records the contract's bundle check reads."""
    records = []
    for key in ("sources", "units", "accounting", "open_questions", "facts", "decisions"):
        for data in values.get(key, {}).values():
            kind = RECORD_TYPES[data["schema"]]
            records.append(kind.model_validate(data, context=FACT_CONTEXT))
    records.append(Brief.model_validate(values["draft_brief"]))
    if values.get("sign_off"):
        records.append(SignOff.model_validate(values["sign_off"]))
    return records
