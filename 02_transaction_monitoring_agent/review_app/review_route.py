"""The review route's actions: the only place a decision or a sign-off is built.

Each one starts from a person who signed in by typed name and role, and from the request the
reviewer was shown. Nothing here, or anywhere else in the application, lets the machine decide.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from fsi_common.records import Assumption, Decision, Person, SignOff
from review_app.drafts import Draft
from review_app.review_model import ReviewModel
from utils.review import ReviewRequest, ReviewResponse

FACT_OUTCOMES = ("accept", "amend", "reject")
SIGN_OUTCOMES = ("signed", "returned")
FINAL_DECISIONS = ("approve", "block")
Today = Callable[[], str]


class ReviewInputError(ValueError):
    """What the reviewer sent cannot be recorded; the message says why and what to do."""


def today() -> str:
    """Return today's date as ``YYYY-MM-DD``."""
    return date.today().isoformat()


def _own_words(text: str | None, what: str) -> str:
    if not text or not text.strip():
        raise ReviewInputError(f"Write {what} in your own words.")
    return text.strip()


def compose_amendment(final: str | None, wording: str | None) -> str:
    """Join the person's own decision and their words into the amendment a decision carries.

    Args:
        final: ``approve`` or ``block``, the person's own decision on the transaction.
        wording: Why, in the person's words.

    Returns:
        ``Approve. <words>`` or ``Block. <words>``.

    Raises:
        ReviewInputError: If the decision is not approve or block, or the words are missing.
    """
    if final not in FINAL_DECISIONS:
        raise ReviewInputError("Choose approve or block for your own decision.")
    words = _own_words(wording, "your own decision")
    return f"{final.capitalize()}. {words}"


def final_of(amendment: str | None) -> str | None:
    """Read the decision an amendment states.

    Args:
        amendment: The amendment of an amend decision.

    Returns:
        ``approve`` or ``block``, or None when the amendment does not open with either.
    """
    if not amendment:
        return None
    first = amendment.split(".", 1)[0].strip().lower()
    return first if first in FINAL_DECISIONS else None


def decide_assessment(
    request: ReviewRequest,
    fact_id: str,
    *,
    outcome: str | None,
    reason: str | None,
    final: str | None,
    wording: str | None,
    person: Person,
    on: str,
) -> Decision:
    """Build a person's decision on one assessment as the request showed it.

    Args:
        request: The request the reviewer was shown.
        fact_id: The assessment decided on; it must be one the brief asks about.
        outcome: ``accept`` (agree with the proposal), ``amend`` (give their own decision) or
            ``reject`` (disagree).
        reason: Why, in the person's words.
        final: For amend, ``approve`` or ``block``.
        wording: For amend, the person's words for their own decision.
        person: The signed-in person.
        on: The date of the decision.

    Returns:
        The decision, tied to the assessment's digest as shown.

    Raises:
        ReviewInputError: If the assessment is not on the brief, the outcome is not one of the
            three, or a required wording is missing.
    """
    cited = {c.fact.id: c for c in request.assessments}
    if fact_id not in cited:
        raise ReviewInputError("That transaction is not on this brief, so nothing was recorded.")
    if outcome not in FACT_OUTCOMES:
        raise ReviewInputError("Choose whether you agree, change or disagree.")
    why = _own_words(reason, "your reason")
    changed = compose_amendment(final, wording) if outcome == "amend" else None
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
    final: str | None,
    answer: str | None,
    reason: str | None,
    person: Person,
    on: str,
) -> Decision:
    """Build a person's answer to one open question.

    Args:
        request: The request the reviewer was shown.
        question_id: The question; it must be on the brief.
        final: ``approve`` or ``block``, the person's own decision on the transaction.
        answer: The answer in the person's words.
        reason: What the answer rests on, in the person's words.
        person: The signed-in person.
        on: The date of the answer.

    Returns:
        The answer decision; its answer reads ``Approve. <words>`` or ``Block. <words>``.

    Raises:
        ReviewInputError: If the question is not on the brief, a wording is missing or the
            decision is not approve or block.
    """
    questions = {q.id: q for q in request.open_questions}
    if question_id not in questions:
        raise ReviewInputError("That question is not on this brief, so nothing was recorded.")
    words = _own_words(answer, "the answer")
    return Decision.on(
        questions[question_id],
        outcome="answer",
        answer=compose_amendment(final, words),
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
        ReviewInputError: If the question is not on the brief or the words are missing.
    """
    if question_id not in {q.id for q in request.open_questions}:
        raise ReviewInputError("That question is not on this brief, so nothing was recorded.")
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
    """Build the response that signs or returns the brief, from the decisions held for it.

    Signing needs every transaction and every question settled and none disagreed with; returning
    needs the reviewer's reason. Decisions held for assessments that have changed since are left
    out.

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
        ReviewInputError: If the brief cannot be signed yet, a decision was made by another
            person, or the return has no reason; the message says what is missing.
    """
    if outcome not in SIGN_OUTCOMES:
        raise ReviewInputError("Choose whether to sign the brief or return it.")
    held = [*model.valid_fact_decisions(draft).values(), *model.valid_answers(draft).values()]
    every = [*draft.facts.values(), *draft.answers.values()]
    others = sorted(
        {f"{d.reviewer.name}, {d.reviewer.role}" for d in every if d.reviewer != person}
    )
    if others:
        raise ReviewInputError(
            f"Decisions on this brief were made by {', '.join(others)}. Sign in as that person "
            "to sign it, or record your own decisions again."
        )
    if outcome == "signed":
        problem = model.cannot_sign_because()
        if problem:
            raise ReviewInputError(problem)
    why = _own_words(reason, "why you are returning the brief") if outcome == "returned" else None
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
