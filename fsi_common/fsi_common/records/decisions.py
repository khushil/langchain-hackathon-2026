"""A person's decisions on facts, statements and questions, and their sign-off of a brief."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, Self

from pydantic import Field, JsonValue, model_validator
from pydantic_core import PydanticCustomError

from fsi_common.ids import digest_json
from fsi_common.records.base import (
    Addressed,
    AnyRecordId,
    BriefId,
    DecisionId,
    Digest,
    IsoDate,
    NonBlank,
    Part,
    Person,
    QuestionId,
    Record,
    SignOffId,
)


class Decision(Record):
    """One person's decision on one record, at the digest of the record they saw.

    ``accept``, ``amend`` and ``reject`` apply to a fact, a statement or a disagreement;
    ``answer`` applies to an open question. The reviewer is always a named person, and the
    schema refuses an empty name and a value that is a model or a program.

    Two digests are kept. ``seen_digest`` is of the whole record as it was on the screen, for
    the audit. ``judged_digest`` is of ``judged``, the part the person judged (for a fact: kind,
    subject, quote, attributes, and each check's name and outcome), so a rerun that finds the
    same fact with another model, prompt, extractor or check wording carries the decision, and a
    rerun that changes what was judged asks again with the difference named.
    """

    SCHEMA: ClassVar[str] = "decision.v1"
    ID_PREFIX: ClassVar[str] = "decision"

    schema_id: Literal["decision.v1"] = Field(default="decision.v1", alias="schema")
    id: DecisionId
    subject_id: AnyRecordId = Field(description="The id of the record decided on")
    seen_digest: Digest = Field(
        description="The digest of the whole record as the person saw it, kept for the audit"
    )
    judged: dict[str, JsonValue] = Field(
        description="What the person judged, as JSON: for a fact its kind, subject, quote, "
        "attributes and each check's name and outcome, with no model, prompt, extractor or "
        "check detail"
    )
    judged_digest: Digest = Field(
        description="The digest of what the person judged; the same fact id with this digest on "
        "a rerun carries the decision"
    )
    outcome: Literal["accept", "amend", "reject", "answer"] = Field(
        description="What the person decided"
    )
    amendment: NonBlank | None = Field(
        default=None, description="For amend: the change, in the person's words"
    )
    answer: NonBlank | None = Field(
        default=None, description="For answer: the answer, in the person's words"
    )
    reason: NonBlank = Field(description="Why, in the person's own words")
    reviewer: Person = Field(description="The person who decided")
    date: IsoDate = Field(description="The date of the decision")

    @classmethod
    def build(cls, *, context: dict[str, Any] | None = None, **fields: Any) -> Self:
        """Build a decision, deriving its judged digest from ``judged`` and its id.

        Args:
            context: Validation context passed on to the checks.
            **fields: Every field except ``id`` and ``judged_digest``.

        Returns:
            The validated decision.

        Raises:
            pydantic.ValidationError: If any field breaks a rule of the record.
        """
        judged = fields.get("judged")
        if isinstance(judged, dict) and "judged_digest" not in fields:
            fields["judged_digest"] = digest_json(judged)
        return super().build(context=context, **fields)

    @classmethod
    def on(
        cls,
        subject: Addressed,
        *,
        outcome: str,
        reason: str,
        reviewer: Any,
        date: str,
        amendment: str | None = None,
        answer: str | None = None,
    ) -> Self:
        """Build a person's decision on a record as they were shown it.

        Args:
            subject: The fact, statement, disagreement or open question decided on.
            outcome: ``accept``, ``amend``, ``reject`` or ``answer``.
            reason: Why, in the person's own words.
            reviewer: The person, as a ``Person`` or its fields.
            date: The date of the decision, ``YYYY-MM-DD``.
            amendment: For amend, the change in the person's words.
            answer: For answer, the answer in the person's words.

        Returns:
            The decision, with both digests taken from the subject.

        Raises:
            pydantic.ValidationError: If any field breaks a rule of the record.
        """
        return cls.build(
            subject_id=subject.id,
            seen_digest=digest_json(subject.to_json()),
            judged=subject.judged_basis(),
            outcome=outcome,
            amendment=amendment,
            answer=answer,
            reason=reason,
            reviewer=reviewer,
            date=date,
        )

    @model_validator(mode="after")
    def _judged_digest_recomputes(self) -> Self:
        expected = digest_json(self.judged)
        if self.judged_digest != expected:
            raise PydanticCustomError(
                "decision.judged-digest",
                "the judged digest {given} does not recompute from what was judged, which gives "
                "{expected}",
                {"given": self.judged_digest, "expected": expected},
            )
        return self

    @model_validator(mode="after")
    def _outcome_fits(self) -> Self:
        is_question = self.subject_id.startswith("question:")
        if (self.outcome == "answer") != is_question:
            raise PydanticCustomError(
                "decision.outcome",
                "an open question is answered, and only a question is: "
                "outcome {outcome} on {subject}",
                {"outcome": self.outcome, "subject": self.subject_id},
            )
        if (self.outcome == "answer") != (self.answer is not None):
            raise PydanticCustomError(
                "decision.outcome", "an answer decision carries the answer, and only it does"
            )
        if (self.outcome == "amend") != (self.amendment is not None):
            raise PydanticCustomError(
                "decision.outcome", "an amend decision carries the amendment, and only it does"
            )
        return self


class Assumption(Part):
    """An open question the reviewer accepts as an assumption, in their own words."""

    question_id: QuestionId = Field(description="The open question accepted as an assumption")
    words: NonBlank = Field(description="The assumption as the reviewer states it")


class SignOff(Record):
    """A named person's signature on, or return of, one brief at the digest they read."""

    SCHEMA: ClassVar[str] = "signoff.v1"
    ID_PREFIX: ClassVar[str] = "signoff"

    schema_id: Literal["signoff.v1"] = Field(default="signoff.v1", alias="schema")
    id: SignOffId
    brief_id: BriefId = Field(description="The brief signed or returned")
    brief_digest: Digest = Field(
        description="The digest of the brief's content as the person read it"
    )
    reviewer: Person = Field(description="The person who signed or returned it")
    date: IsoDate = Field(description="The date of the sign-off")
    outcome: Literal["signed", "returned"] = Field(
        description="Signed as fit to act on, or returned"
    )
    assumptions: list[Assumption] = Field(
        description="Each open question the reviewer accepts as an assumption, in their words"
    )
    reason: NonBlank | None = Field(
        default=None, description="For returned: why, in the person's words"
    )

    @model_validator(mode="after")
    def _outcome_fits(self) -> Self:
        if (self.outcome == "returned") != (self.reason is not None):
            raise PydanticCustomError(
                "signoff.reason", "a returned brief carries the reason, and only then"
            )
        ids = [a.question_id for a in self.assumptions]
        if len(ids) != len(set(ids)):
            raise PydanticCustomError(
                "signoff.assumptions", "an open question is accepted as an assumption twice"
            )
        return self
