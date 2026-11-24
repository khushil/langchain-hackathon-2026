"""Open questions (the gap register) and disagreements, settled by a person and by no record."""

from __future__ import annotations

from typing import ClassVar, Literal, Self

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

from fsi_common.records.base import (
    AnyRecordId,
    DecisionId,
    DisagreementId,
    Extractor,
    FactId,
    NonBlank,
    QuestionId,
    Record,
    SourceRef,
)

GapReason = Literal[
    "no_source",
    "missing_data",
    "ambiguous_meaning",
    "contradiction",
    "unresolved_reference",
    "placeholder",
    "unreadable",
    "inferred_only",
]
"""Why a question is open. The one closed list, with these meanings:

- ``no_source``: nothing in the sources read addresses the question.
- ``missing_data``: the answer needs a value about the subject (a firm, a customer, an account)
  that the records do not hold.
- ``ambiguous_meaning``: the text allows more than one reading.
- ``contradiction``: two sources, or two places in one source, disagree.
- ``unresolved_reference``: the source cites something that was not found.
- ``placeholder``: a value is a placeholder rather than a value.
- ``unreadable``: a unit could not be read.
- ``inferred_only``: the answer rests only on an inference.
"""

QuestionState = Literal["open", "asked", "answered", "accepted", "closed_no_answer"]
"""Where a question stands; answered, accepted and closed with no answer need a decision."""

SETTLED_STATES = frozenset({"answered", "accepted", "closed_no_answer"})


class OpenQuestion(Record):
    """Something the sources do not settle, written as a question one named role can answer.

    The id is derived from the subject and the question text, so a rebuild asks the same question
    under the same id and an earlier answer still attaches to it.
    """

    SCHEMA: ClassVar[str] = "open_question.v1"
    ID_PREFIX: ClassVar[str] = "question"
    ID_EXCLUDES: ClassVar[frozenset[str]] = frozenset({"id", "schema_id", "state", "decision_id"})

    schema_id: Literal["open_question.v1"] = Field(default="open_question.v1", alias="schema")
    id: QuestionId
    about: SourceRef = Field(description="The source unit the question concerns")
    question: NonBlank = Field(
        description="The question as it would be put to the person, answerable in one reply"
    )
    why_unknown: NonBlank = Field(description="What was looked for, where, and what was found")
    impact: NonBlank = Field(description="What changes with the answer")
    ask_role: NonBlank = Field(
        description="The role to ask, for example 'Head of Third-Party Risk'"
    )
    reason: GapReason = Field(description="Why the question is open, from the closed list")
    cites: list[AnyRecordId] = Field(description="The facts and units the question rests on")
    priority: Literal["high", "medium", "low"] = Field(
        description="The order of review; a low priority never removes a question from the register"
    )
    state: QuestionState = Field(description="Where the question stands")
    decision_id: DecisionId | None = Field(
        default=None, description="The person's decision that answered or closed the question"
    )

    @model_validator(mode="after")
    def _settled_by_a_person(self) -> Self:
        if not self.cites and self.reason != "no_source":
            raise PydanticCustomError(
                "question.cites",
                "a question with reason {reason} cites what it rests on",
                {"reason": self.reason},
            )
        if self.state in SETTLED_STATES and self.decision_id is None:
            raise PydanticCustomError(
                "question.state",
                "a question in state {state} needs the person's decision that settled it",
                {"state": self.state},
            )
        if self.state not in SETTLED_STATES and self.decision_id is not None:
            raise PydanticCustomError(
                "question.state",
                "a question in state {state} cannot carry a decision",
                {"state": self.state},
            )
        return self


class Disagreement(Record):
    """Two or more facts that differ about the same thing, kept side by side.

    The record names no winner and has no field that could: a person reconciles it by a decision,
    and the facts stay as they are.
    """

    SCHEMA: ClassVar[str] = "disagreement.v1"
    ID_PREFIX: ClassVar[str] = "disagreement"
    ID_EXCLUDES: ClassVar[frozenset[str]] = frozenset(
        {"id", "schema_id", "status", "decision_id", "found_by"}
    )

    schema_id: Literal["disagreement.v1"] = Field(default="disagreement.v1", alias="schema")
    id: DisagreementId
    about: NonBlank = Field(description="What the facts disagree on, in plain words")
    claims: list[FactId] = Field(description="The differing facts, two or more")
    found_by: Extractor = Field(description="The comparison that found the difference")
    status: Literal["open", "reconciled"] = Field(description="Whether a person has reconciled it")
    decision_id: DecisionId | None = Field(
        default=None, description="The person's decision that reconciled it"
    )

    @model_validator(mode="after")
    def _side_by_side(self) -> Self:
        if len(set(self.claims)) < 2 or len(set(self.claims)) != len(self.claims):
            raise PydanticCustomError(
                "disagreement.claims",
                "a disagreement holds two or more different facts; it holds {count}",
                {"count": len(set(self.claims))},
            )
        if (self.status == "reconciled") != (self.decision_id is not None):
            raise PydanticCustomError(
                "disagreement.status",
                "a reconciled disagreement needs a person's decision, and only then",
            )
        return self
