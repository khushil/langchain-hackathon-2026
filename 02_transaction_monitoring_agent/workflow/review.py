"""The review step: the brief put to a named person, and what they send back, validated and kept."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from fsi_common.records import (
    RECORD_TYPES,
    SETTLED_STATES,
    Fact,
    OpenQuestion,
    Record,
    carry_over,
    judged_digest,
    record_digest,
)
from utils.records import FACT_CONTEXT
from utils.review import (
    NOT_ANSWERED,
    CitedFact,
    Customer,
    ReviewMismatchError,
    ReviewRequest,
    ReviewResponse,
    ReviewStatement,
    final_of,
)
from workflow.decisions import latest_by_subject, load_decisions, save_decisions, save_sign_off
from workflow.errors import UnitNotHeldError
from workflow.requests import request_of
from workflow.state import MonitorState

BRIEF_SCHEMA = "brief.v1"


def _unit_text(state: MonitorState, fact: Fact) -> str:
    for unit in state["units"].values():
        if (unit["source_id"], unit["anchor"]) == (fact.subject.source_id, fact.subject.anchor):
            return state["unit_text"][unit["id"]]
    raise UnitNotHeldError(
        f"Fact {fact.id} cites {fact.subject.anchor}, which is not a unit of this run."
    )


def _settled_by_earlier(question: OpenQuestion, earlier: Mapping[str, Record]) -> OpenQuestion:
    # A question's id is derived from the content a person judges, so an earlier answer under the
    # same id was given to this very question and needs no second comparison.
    decision = earlier.get(question.id)
    if (
        decision is not None
        and decision.outcome == "answer"
        and question.state not in SETTLED_STATES
    ):
        return OpenQuestion.model_validate(
            {**question.to_json(), "state": "answered", "decision_id": decision.id}
        )
    return question


def _questions(state: MonitorState, earlier: Mapping[str, Record]) -> list[OpenQuestion]:
    held = (OpenQuestion.model_validate(q) for q in state.get("open_questions", {}).values())
    return [_settled_by_earlier(q, earlier) for q in held]


def _customer(state: MonitorState) -> Customer:
    user_id = request_of(state)["user_id"]
    for data in state["facts"].values():
        fact = Fact.model_validate(data, context=FACT_CONTEXT)
        if fact.kind == "customer_attribute" and fact.attributes["field"] == "name":
            return Customer(user_id=user_id, name=fact.attributes["value"])
    return Customer(user_id=user_id, name=user_id)


def build_review_request(state: MonitorState, earlier: Mapping[str, Record]) -> ReviewRequest:
    """Build the payload the reviewer is shown: the brief, each fact with its line and carry.

    Args:
        state: The graph state, holding the draft brief, the facts, the units and the questions.
        earlier: The latest earlier decision on each subject id, from the store.

    Returns:
        The review request. Each cited fact carries what ``carry_over`` gives for the latest
        earlier decision on it, and ``history`` lists what reviewers decided about the customer
        before, whatever transaction it was about.
    """
    brief = RECORD_TYPES[BRIEF_SCHEMA].model_validate(state["draft_brief"])
    statements = []
    for statement in brief.statements:
        cited = []
        for fact_id in statement.cites:
            fact = Fact.model_validate(state["facts"][fact_id], context=FACT_CONTEXT)
            cited.append(
                CitedFact(
                    fact=fact,
                    seen_digest=record_digest(fact),
                    unit_text=_unit_text(state, fact),
                    carry=carry_over(earlier.get(fact.id), fact),
                )
            )
        statements.append(
            ReviewStatement(
                statement_id=statement.id,
                heading=statement.heading,
                text=statement.text,
                facts=cited,
            )
        )
    history = sorted(earlier.values(), key=lambda d: (d.date, d.id))
    return ReviewRequest(
        brief_id=brief.id,
        brief_digest=brief.content_digest,
        request=brief.request,
        customer=_customer(state),
        statements=statements,
        open_questions=_questions(state, earlier),
        history=history,
    )


def _shown(request: ReviewRequest, state: MonitorState) -> dict[str, tuple[str, set[str]]]:
    """Each subject the reviewer was shown, with its judged digest and the seen digests allowed.

    A question another run has answered since this one was put to the reviewer reads as answered
    when the request is built again on resume, though the reviewer was shown it open; both
    versions of it are the question as shown. Only an assessment is decided: a profile field the
    brief cites is read, and a decision on it was never asked for.
    """
    shown: dict[str, tuple[str, set[str]]] = {}
    for cited in request.assessments:
        shown[cited.fact.id] = (judged_digest(cited.fact), {cited.seen_digest})
    held = state.get("open_questions", {})
    for question in request.open_questions:
        seen = {record_digest(question)}
        if question.id in held:
            seen.add(record_digest(OpenQuestion.model_validate(held[question.id])))
        shown[question.id] = (judged_digest(question), seen)
    return shown


def _check_sign_off_against_questions(response: ReviewResponse, request: ReviewRequest) -> None:
    """Refuse a sign-off that leaves an open question unrecorded, or names one the brief lacks."""
    sign_off = response.sign_off
    if sign_off is None:
        return
    held = {question.id for question in request.open_questions}
    accepted = {assumption.question_id for assumption in sign_off.assumptions}
    unknown = sorted(accepted - held)
    if unknown:
        raise ReviewMismatchError(
            f"The sign-off accepts an assumption on {', '.join(unknown)}, which the brief does "
            "not carry as an open question."
        )
    if sign_off.outcome != "signed":
        return
    answered = {
        d.subject_id
        for d in response.decisions
        if d.outcome == "answer" and final_of(d.answer) is not None
    }
    unrecorded = [
        question.id
        for question in request.open_questions
        if question.state not in SETTLED_STATES and question.id not in answered
    ]
    if unrecorded:
        raise ReviewMismatchError(
            f"The brief was signed with open question(s) {', '.join(unrecorded)} "
            f"{NOT_ANSWERED}. A question about a transaction is settled only by an answer that "
            "says approve or block; an assumption does not settle it."
        )


def _check_sign_off_against_assessments(response: ReviewResponse, request: ReviewRequest) -> None:
    """Refuse a signed sign-off unless every assessment has a person's decision, none a rejection.

    An assessment is decided when the response holds a decision on it, or when an earlier
    decision on the same content is carried; one asked again counts as undecided.
    """
    sign_off = response.sign_off
    if sign_off is None or sign_off.outcome != "signed":
        return
    sent = {d.subject_id: d for d in response.decisions}
    waiting, rejected = [], []
    for cited in request.assessments:
        decision = sent.get(cited.fact.id)
        if decision is None and cited.carry.outcome == "carried":
            decision = cited.carry.decision
        if decision is None:
            waiting.append(cited.fact.subject.anchor)
        elif decision.outcome == "reject":
            rejected.append(cited.fact.subject.anchor)
    if waiting:
        raise ReviewMismatchError(
            f"The brief was signed with no decision on {', '.join(waiting)}; a signed brief "
            "needs a person's decision on every assessment."
        )
    if rejected:
        raise ReviewMismatchError(
            f"The brief was signed with {', '.join(rejected)} rejected; a brief with a rejected "
            "assessment can be returned but not signed."
        )


def validate_response(
    response: ReviewResponse, request: ReviewRequest, state: MonitorState
) -> None:
    """Confirm a review response answers the request the reviewer was shown.

    Args:
        response: What the application received from the reviewer.
        request: The payload the reviewer was shown.
        state: The graph state, to read the questions the reviewer saw.

    Raises:
        ReviewMismatchError: If the sign-off is for another brief or digest, or a decision is on
            something the reviewer was not asked to decide, or on a version of it that has since
            changed, or a signed sign-off leaves an open question neither answered, already
            settled nor accepted as an assumption, or accepts an assumption on a question the
            brief lacks, or a signed sign-off leaves an assessment without a decision or with a
            rejected one.
    """
    response.check_against(request)
    shown = _shown(request, state)
    for decision in response.decisions:
        if decision.subject_id not in shown:
            raise ReviewMismatchError(
                f"Decision {decision.id} is on {decision.subject_id}, which the reviewer was not "
                "asked to decide."
            )
        judged, seen = shown[decision.subject_id]
        if decision.judged_digest != judged or decision.seen_digest not in seen:
            raise ReviewMismatchError(
                f"Decision {decision.id} is on {decision.subject_id} as it was before it "
                "changed, not as the reviewer was shown it."
            )
    _check_sign_off_against_questions(response, request)
    _check_sign_off_against_assessments(response, request)


def apply_response(
    response: ReviewResponse, request: ReviewRequest, earlier: Mapping[str, Record]
) -> dict[str, Any]:
    """Return the state update for a validated review response.

    Decisions the reviewer made, and the earlier decisions the request carried, go into the
    state's decisions; an earlier decision is left out when the reviewer decided the same fact
    again, so a fact has one decision in the run; each question a decision answers moves to
    answered; a sign-off, when sent, is stored as it is.

    Args:
        response: The validated response.
        request: The payload the reviewer was shown.
        earlier: The latest earlier decision on each subject id, from the store.

    Returns:
        The update for ``decisions``, ``open_questions`` and, when sent, ``sign_off``.
    """
    decisions = {d.id: d.to_json() for d in response.decisions}
    decided = {d.subject_id for d in response.decisions}
    carried = [
        cited.carry.decision
        for cited in request.assessments
        if cited.carry.outcome == "carried"
        and cited.carry.decision is not None
        and cited.fact.id not in decided
    ]
    answers = {d.subject_id: d for d in response.decisions if d.outcome == "answer"}
    questions = {}
    for question in request.open_questions:
        answer = answers.get(question.id)
        if answer is not None:
            question = OpenQuestion.model_validate(
                {**question.to_json(), "state": "answered", "decision_id": answer.id}
            )
        elif question.decision_id is not None:
            carried.append(earlier[question.id])
        questions[question.id] = question.to_json()
    decisions.update({d.id: d.to_json() for d in carried})
    update: dict[str, Any] = {"decisions": decisions, "open_questions": questions}
    if response.sign_off is not None:
        update["sign_off"] = response.sign_off.to_json()
    return update


def make_review_step() -> Callable[..., dict[str, Any]]:
    """Build the review step, which stops for a named reviewer and records what they send back.

    Returns:
        The graph node. It reads earlier decisions from the store, puts the brief to the reviewer
        with ``interrupt``, and on resume validates the response, stores its decisions and
        sign-off, and updates the state. Nothing here builds a decision or a sign-off.
    """

    def review_step(state: MonitorState, *, store: BaseStore) -> dict[str, Any]:
        user_id = request_of(state)["user_id"]
        earlier = latest_by_subject(load_decisions(store, user_id))
        review_request = build_review_request(state, earlier)
        value = interrupt(review_request.to_payload())
        response = ReviewResponse.model_validate(value, context=FACT_CONTEXT)
        validate_response(response, review_request, state)
        save_decisions(store, user_id, response.decisions)
        if response.sign_off is not None:
            save_sign_off(store, user_id, response.sign_off)
        return apply_response(response, review_request, earlier)

    return review_step


__all__ = ["CitedFact", "make_review_step", "build_review_request", "validate_response"]
