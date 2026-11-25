"""The review interrupt's payload and resume value, and the store namespaces for decisions.

The workflow stops at the review with a ``ReviewRequest``: the brief as the reviewer will read it,
each assessment beside its transaction's line, what an earlier decision made of it, and what
reviewers have said about the customer before. It resumes with a ``ReviewResponse`` that only the
reviewer's application builds, from a signed-in person's request.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from fsi_common.records import (
    CarryOver,
    Decision,
    Fact,
    OpenQuestion,
    Person,
    SignOff,
    carry_over,
    record_digest,
)
from fsi_common.records.base import BriefId, Digest, NonBlank, Part, StatementId

STORE_ROOT = "transaction-monitoring"
FINAL_DECISIONS = ("approve", "block")
NOT_ANSWERED = "not answered with approve or block"
"""The words both the engine and the application use for a question nobody has answered with a
decision: a question about a transaction is settled only by an answer that says approve or block,
and an assumption alone never settles it."""
ASSESSMENT_KIND = "transaction_assessment"


class ReviewMismatchError(ValueError):
    """A review response does not answer the request the reviewer was shown."""


class InvalidNamespaceLabelError(ValueError):
    """A store namespace label is empty or holds a full stop, which LangGraph's store refuses."""


class CitedFact(Part):
    """One fact as the reviewer sees it, beside its source line and any earlier decision.

    ``carry`` says what became of the latest earlier decision on the fact's id: carried (shown as
    decided, with its date and reviewer), ask again (shown with the earlier decision and what
    changed), or fresh. It must be what ``carry_over`` gives for that decision and this fact.
    """

    fact: Fact = Field(description="The fact")
    seen_digest: Digest = Field(description="The digest a decision on this fact must carry")
    unit_text: NonBlank = Field(description="The full line of the data file the fact quotes")
    carry: CarryOver = Field(description="What becomes of the earlier decision on this fact")

    @model_validator(mode="after")
    def _digest_is_the_facts(self) -> CitedFact:
        if self.seen_digest != record_digest(self.fact):
            raise ValueError(f"seen_digest is not the digest of fact {self.fact.id}")
        if self.carry != carry_over(self.carry.decision, self.fact):
            raise ValueError(f"carry is not what carry_over gives for fact {self.fact.id}")
        return self

    @property
    def needs_decision(self) -> bool:
        """Whether a person decides on this fact: an assessment does, a profile field does not."""
        return self.fact.kind == ASSESSMENT_KIND


class ReviewStatement(Part):
    """One statement of the brief with every fact it cites."""

    statement_id: StatementId
    heading: NonBlank | None = None
    text: NonBlank
    facts: list[CitedFact] = Field(min_length=1)


class Customer(Part):
    """The customer a brief is about."""

    user_id: NonBlank
    name: NonBlank


class ReviewRequest(Part):
    """The review interrupt's payload: the brief as the reviewer will read and sign it."""

    brief_id: BriefId
    brief_digest: Digest
    request: NonBlank
    customer: Customer
    statements: list[ReviewStatement] = Field(min_length=1)
    open_questions: list[OpenQuestion]
    history: list[Decision] = Field(
        description="What reviewers decided about this customer's transactions before, the latest "
        "decision on each"
    )

    def to_payload(self) -> dict[str, Any]:
        """Return the payload as JSON for ``interrupt()``.

        Returns:
            The request as a dict of JSON values.
        """
        return self.model_dump(mode="json", by_alias=True)

    @property
    def assessments(self) -> list[CitedFact]:
        """The assessments a person decides, each once, in the order the brief cites them."""
        seen: dict[str, CitedFact] = {}
        for statement in self.statements:
            for cited in statement.facts:
                if cited.needs_decision:
                    seen.setdefault(cited.fact.id, cited)
        return list(seen.values())


class ReviewResponse(Part):
    """The value the review interrupt resumes with: the reviewer and what they decided."""

    reviewer: Person
    decisions: list[Decision]
    sign_off: SignOff | None = None

    @model_validator(mode="after")
    def _one_reviewer(self) -> ReviewResponse:
        people = {(d.reviewer.name, d.reviewer.role) for d in self.decisions}
        if self.sign_off is not None:
            people.add((self.sign_off.reviewer.name, self.sign_off.reviewer.role))
        if people - {(self.reviewer.name, self.reviewer.role)}:
            raise ValueError("every decision and the sign-off are the reviewer's own")
        return self

    def check_against(self, request: ReviewRequest) -> None:
        """Confirm the response answers this request: its sign-off is for this brief at this digest.

        Args:
            request: The payload the reviewer was shown.

        Raises:
            ReviewMismatchError: If the sign-off names another brief or another digest.
        """
        if self.sign_off is not None and (self.sign_off.brief_id, self.sign_off.brief_digest) != (
            request.brief_id,
            request.brief_digest,
        ):
            raise ReviewMismatchError(
                "the sign-off is not for the brief and digest the reviewer was shown"
            )


def final_of(words: str | None) -> str | None:
    """Read the decision a person's words open with.

    Args:
        words: An amendment or an answer, which the review route writes as ``Approve. <words>`` or
            ``Block. <words>``.

    Returns:
        ``approve`` or ``block``, or None when the words do not open with either.
    """
    if not words:
        return None
    first = words.split(".", 1)[0].strip().lower()
    return first if first in FINAL_DECISIONS else None


def settles(decision: Decision) -> bool:
    """Say whether a person's decision settles a transaction.

    A transaction is settled by a person's approve or block: agreeing with the proposal, an
    amendment or an answer that opens with ``Approve.`` or ``Block.``. Disagreeing with a proposal
    settles nothing, and neither does an amendment or an answer in other words.

    Args:
        decision: The decision on an assessment or on a question.

    Returns:
        True when the decision stands as an approve or a block.
    """
    match decision.outcome:
        case "accept":
            return True
        case "amend":
            return final_of(decision.amendment) is not None
        case "answer":
            return final_of(decision.answer) is not None
        case _:
            return False


def _labels(*labels: str) -> tuple[str, ...]:
    for label in labels:
        if not label or "." in label:
            raise InvalidNamespaceLabelError(f"'{label}' cannot be a store namespace label")
    return labels


def decisions_namespace(user_id: str) -> tuple[str, ...]:
    """Return the store namespace of the decisions made about a customer, read again on a rerun.

    Args:
        user_id: The customer, for example ``USR-001``.

    Returns:
        ``("transaction-monitoring", "decisions", user_id)``; items are keyed by decision id.

    Raises:
        InvalidNamespaceLabelError: If the label is empty or holds a full stop.
    """
    return _labels(STORE_ROOT, "decisions", user_id)


def sign_offs_namespace(user_id: str) -> tuple[str, ...]:
    """Return the store namespace of the sign-offs of briefs about a customer.

    Args:
        user_id: The customer.

    Returns:
        ``("transaction-monitoring", "sign-offs", user_id)``; items are keyed by sign-off id.

    Raises:
        InvalidNamespaceLabelError: If the label is empty or holds a full stop.
    """
    return _labels(STORE_ROOT, "sign-offs", user_id)
