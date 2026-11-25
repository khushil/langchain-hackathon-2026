"""The review route's actions: the only place a decision or a sign-off is built.

Each one starts from a person who signed in by typed name and role, and from the request the
reviewer was shown. Nothing here, or anywhere else in the application, lets the machine decide.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from fsi_common.records import Addressed, Assumption, Brief, Decision, Person, SignOff
from review_app.drafts import Draft
from review_app.profile import is_profile
from review_app.review_model import ReviewModel
from utils.state import ReviewRequest, ReviewResponse

FACT_OUTCOMES = ("accept", "amend", "reject")
SIGN_OUTCOMES = ("signed", "returned")
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


def decide_fact(
    request: ReviewRequest,
    fact_id: str,
    *,
    outcome: str,
    reason: str | None,
    amendment: str | None,
    person: Person,
    on: str,
) -> Decision:
    """Build a person's decision on one fact as the request showed it.

    Args:
        request: The request the reviewer was shown.
        fact_id: The fact decided on; it must be cited in the request.
        outcome: ``accept``, ``amend`` or ``reject``.
        reason: Why, in the person's words.
        amendment: For amend, the wording the person gives.
        person: The signed-in person.
        on: The date of the decision.

    Returns:
        The decision, tied to the fact's digest as shown.

    Raises:
        ReviewInputError: If the fact is not on the brief, the outcome is not one of the three,
            or a required wording is missing.
    """
    cited = {c.fact.id: c for s in request.statements for c in s.facts}
    if fact_id not in cited:
        raise ReviewInputError("That fact is not on this brief, so nothing was recorded.")
    if outcome not in FACT_OUTCOMES:
        raise ReviewInputError("Choose accept, amend or reject.")
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


def decide_profile(
    request: ReviewRequest,
    *,
    outcome: str,
    reason: str | None,
    amendment: str | None,
    person: Person,
    on: str,
) -> list[Decision]:
    """Build a person's one decision on the firm profile as a decision on each fact it covers.

    Every decision carries the same outcome, reason, wording, reviewer and date, so that the
    pages can show them as one decision on the profile.

    Args:
        request: The request the reviewer was shown.
        outcome: ``accept``, ``amend`` or ``reject``.
        reason: Why, in the person's words.
        amendment: For amend, the wording the person gives for the profile.
        person: The signed-in person.
        on: The date of the decision.

    Returns:
        One decision for each firm or provider fact the brief cites, in the brief's order.

    Raises:
        ReviewInputError: If the brief cites no firm or provider fact, the outcome is not one of
            the three, or a required wording is missing.
    """
    covered = {c.fact.id: c.fact for s in request.statements for c in s.facts if is_profile(c.fact)}
    if not covered:
        raise ReviewInputError(
            "The brief cites no firm or provider facts, so there is no profile to decide."
        )
    if outcome not in FACT_OUTCOMES:
        raise ReviewInputError("Choose accept, amend or reject.")
    why = _own_words(reason, "your reason")
    changed = _own_words(amendment, "the amended wording") if outcome == "amend" else None
    return [
        Decision.on(fact, outcome=outcome, reason=why, amendment=changed, reviewer=person, date=on)
        for fact in covered.values()
    ]


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
        question_id: The question; it must be on the brief.
        answer: The answer in the person's words.
        reason: What the answer rests on, in the person's words.
        person: The signed-in person.
        on: The date of the answer.

    Returns:
        The answer decision.

    Raises:
        ReviewInputError: If the question is not on the brief or a wording is missing.
    """
    questions = {q.id: q for q in request.open_questions}
    if question_id not in questions:
        raise ReviewInputError("That question is not on this brief, so nothing was recorded.")
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

    Signing needs every fact and every question settled and no fact rejected; returning needs
    the reviewer's reason. Decisions held for facts that have changed since are left out.

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


def decide_assessment(
    assessment: Addressed,
    *,
    outcome: str,
    reason: str | None,
    amendment: str | None,
    person: Person,
    on: str,
) -> Decision:
    """Build a person's decision on one policy assessment as the page showed it.

    Args:
        assessment: The assessment decided on; its id is made from its content, so a decision
            on an assessment that has since changed names another record.
        outcome: ``accept``, ``amend`` or ``reject``.
        reason: Why, in the person's words.
        amendment: For amend, the wording the person gives.
        person: The signed-in person.
        on: The date of the decision.

    Returns:
        The decision, tied to the assessment's digest as shown.

    Raises:
        ReviewInputError: If the outcome is not one of the three or a required wording is missing.
    """
    if outcome not in FACT_OUTCOMES:
        raise ReviewInputError("Choose accept, amend or reject.")
    why = _own_words(reason, "your reason")
    changed = _own_words(amendment, "the amended wording") if outcome == "amend" else None
    return Decision.on(
        assessment, outcome=outcome, reason=why, amendment=changed, reviewer=person, date=on
    )


def sign_gap_report(
    report: Brief,
    *,
    outcome: str,
    reason: str | None,
    person: Person,
    on: str,
) -> SignOff:
    """Build a person's signature on, or return of, a gap report at the digest they read.

    Args:
        report: The gap report, a brief.
        outcome: ``signed`` or ``returned``.
        reason: For returned, why, in the person's words.
        person: The signed-in person.
        on: The date.

    Returns:
        The sign-off.

    Raises:
        ReviewInputError: If the outcome is not one of the two or a return has no reason.
    """
    if outcome not in SIGN_OUTCOMES:
        raise ReviewInputError("Choose whether to sign the gap report or return it.")
    why = (
        _own_words(reason, "why you are returning the gap report")
        if outcome == "returned"
        else None
    )
    return SignOff.build(
        brief_id=report.id,
        brief_digest=report.content_digest,
        reviewer=person,
        date=on,
        outcome=outcome,
        assumptions=[],
        reason=why,
    )
