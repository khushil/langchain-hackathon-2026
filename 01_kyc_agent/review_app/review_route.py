"""The review route's actions: the only place a decision or a sign-off is built.

Each one starts from a person who signed in by typed name and role, and from the request the
reviewer was shown. Nothing here, or anywhere else in the application, lets the machine decide.
"""

from __future__ import annotations

from fsi_common.records import Assumption, Decision, Person, SignOff
from review_app.drafts import Draft
from review_app.review_model import ReviewModel
from utils.kyc_state import ReviewRequest, ReviewResponse

FACT_OUTCOMES = ("accept", "amend", "reject")
SIGN_OUTCOMES = ("signed", "returned")
CHOOSE = "Choose accept, amend or reject."


class ReviewInputError(ValueError):
    """What the reviewer sent cannot be recorded; the message says why and what to do."""


def _own_words(text: str | None, what: str) -> str:
    if not text or not text.strip():
        raise ReviewInputError(f"Write {what} in your own words.")
    return text.strip()


def _proposals(request: ReviewRequest) -> dict:
    return {c.fact.id: c for s in request.statements for c in s.facts if c.fact.kind == "proposal"}


def decide_proposal(
    request: ReviewRequest,
    fact_id: str,
    *,
    outcome: str,
    reason: str | None,
    amendment: str | None,
    person: Person,
    on: str,
) -> Decision:
    """Build a person's decision on one application's proposal as the request showed it.

    Args:
        request: The request the reviewer was shown.
        fact_id: The proposal decided on; it must be one the request cites.
        outcome: ``accept``, ``amend`` or ``reject``.
        reason: Why, in the person's words.
        amendment: For amend, the risk level and decision the person gives, in their words.
        person: The signed-in person.
        on: The date of the decision.

    Returns:
        The decision, tied to the proposal's digest as shown.

    Raises:
        ReviewInputError: If the fact is not on the batch or is not a proposal, the outcome is not
            one of the three, or a required wording is missing.
    """
    cited = {c.fact.id: c for s in request.statements for c in s.facts}
    if fact_id not in cited:
        raise ReviewInputError("That fact is not on this batch, so nothing was recorded.")
    if fact_id not in _proposals(request):
        raise ReviewInputError("That is not a proposal, so there is no decision to record on it.")
    if outcome not in FACT_OUTCOMES:
        raise ReviewInputError(CHOOSE)
    why = _own_words(reason, "your reason")
    changed = _own_words(amendment, "the amended wording") if outcome == "amend" else None
    return Decision.on(
        cited[fact_id].fact,
        outcome=outcome,
        reason=why,
        amendment=changed,
        reviewer=person,
        date=on,
    )


def answer_question(
    request: ReviewRequest,
    question_id: str,
    *,
    answer: str | None,
    reason: str | None,
    person: Person,
    on: str,
) -> Decision:
    """Build a person's answer to one open question.

    Args:
        request: The request the reviewer was shown.
        question_id: The question; it must be on the batch.
        answer: The answer in the person's words.
        reason: What the answer rests on, in the person's words.
        person: The signed-in person.
        on: The date of the answer.

    Returns:
        The answer decision.

    Raises:
        ReviewInputError: If the question is not on the batch or a wording is missing.
    """
    questions = {q.id: q for q in request.open_questions}
    if question_id not in questions:
        raise ReviewInputError("That question is not on this batch, so nothing was recorded.")
    return Decision.on(
        questions[question_id],
        outcome="answer",
        answer=_own_words(answer, "the answer"),
        reason=_own_words(reason, "what the answer rests on"),
        reviewer=person,
        date=on,
    )


def check_assumption(request: ReviewRequest, question_id: str, words: str | None) -> str:
    """Check an assumption the reviewer accepts for a question and return its words.

    Args:
        request: The request the reviewer was shown.
        question_id: The question.
        words: The assumption in the reviewer's words.

    Returns:
        The words, trimmed.

    Raises:
        ReviewInputError: If the question is not on the batch or the words are missing.
    """
    if question_id not in {q.id for q in request.open_questions}:
        raise ReviewInputError("That question is not on this batch, so nothing was recorded.")
    return _own_words(words, "the assumption")


def build_response(
    request: ReviewRequest,
    model: ReviewModel,
    draft: Draft,
    *,
    outcome: str,
    reason: str | None,
    person: Person,
    on: str,
) -> ReviewResponse:
    """Build the response that signs or returns the batch, from the decisions held for it.

    Signing needs every proposal and every question settled and no proposal rejected; returning
    needs the reviewer's reason. Decisions held for proposals that have changed since are left out.

    Args:
        request: The request the reviewer was shown.
        model: The review as the pages show it, which says what is settled.
        draft: The decisions and assumptions held so far.
        outcome: ``signed`` or ``returned``.
        reason: For returned, why, in the person's words.
        person: The signed-in person; every decision sent must be theirs.
        on: The date.

    Returns:
        The response to submit.

    Raises:
        ReviewInputError: If the batch cannot be signed yet, a decision was made by another
            person, or the return has no reason; the message says what is missing.
    """
    if outcome not in SIGN_OUTCOMES:
        raise ReviewInputError("Choose whether to sign the batch or return it.")
    held = [*model.valid_fact_decisions(draft).values(), *model.valid_answers(draft).values()]
    every = [*draft.facts.values(), *draft.answers.values()]
    others = sorted(
        {f"{d.reviewer.name}, {d.reviewer.role}" for d in every if d.reviewer != person}
    )
    if others:
        raise ReviewInputError(
            f"Decisions on this batch were made by {', '.join(others)}. Sign in as that person "
            "to sign it, or record your own decisions again."
        )
    if outcome == "signed":
        problem = model.cannot_sign_because()
        if problem:
            raise ReviewInputError(problem)
    why = _own_words(reason, "why you are returning the batch") if outcome == "returned" else None
    assumptions = [
        Assumption(question_id=q, words=w) for q, w in model.valid_assumptions(draft).items()
    ]
    sign_off = SignOff.build(
        brief_id=request.brief_id,
        brief_digest=request.brief_digest,
        reviewer=person,
        date=on,
        outcome=outcome,
        assumptions=assumptions,
        reason=why,
    )
    response = ReviewResponse(reviewer=person, decisions=held, sign_off=sign_off)
    response.check_against(request)
    return response
