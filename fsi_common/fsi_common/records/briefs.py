"""Briefs: statements written for a request, each citing the facts it rests on."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, Self

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_core import PydanticCustomError

from fsi_common.ids import DIGEST_PREFIX, ID_HEX_LENGTH, digest_json
from fsi_common.records.base import (
    DRAFT_CONTEXT_KEY,
    Addressed,
    BriefId,
    Digest,
    FactId,
    NonBlank,
    QuestionId,
    Record,
    SourceId,
    StatementId,
    VersionTag,
)


class Statement(Addressed):
    """One statement of a brief and the facts it cites."""

    ID_PREFIX: ClassVar[str] = "statement"

    id: StatementId
    heading: NonBlank | None = Field(
        default=None, description="The part of the brief the statement sits under"
    )
    text: NonBlank = Field(description="The statement as the brief gives it")
    cites: list[FactId] = Field(description="The facts the statement rests on, one or more")

    @field_validator("cites")
    @classmethod
    def _cites_a_fact(cls, value: list[str]) -> list[str]:
        if not value:
            raise PydanticCustomError("brief.statement-cites", "the statement cites no fact")
        if len(value) != len(set(value)):
            raise PydanticCustomError("brief.statement-cites", "the statement cites a fact twice")
        return value


class Brief(Record):
    """A brief written for one request from facts only, with the digest the reviewer signs against.

    The digest covers the request, the sources, the statements and the open questions carried, so
    any change to what the reviewer reads changes the digest; the id is the digest's first 16 hex
    characters. The model and prompt versions are recorded beside the content, outside the digest.
    """

    SCHEMA: ClassVar[str] = "brief.v1"
    ID_PREFIX: ClassVar[str] = "brief"
    ID_EXCLUDES: ClassVar[frozenset[str]] = frozenset(
        {"id", "schema_id", "content_digest", "model", "prompt_version"}
    )

    schema_id: Literal["brief.v1"] = Field(default="brief.v1", alias="schema")
    id: BriefId
    request: NonBlank = Field(description="The request the brief answers, as it was made")
    sources: list[SourceId] = Field(
        min_length=1, description="The sources the brief was written from"
    )
    statements: list[Statement] = Field(
        min_length=1, description="The brief's statements, in order"
    )
    open_question_ids: list[QuestionId] = Field(
        description="The open questions the brief carries to the reviewer"
    )
    content_digest: Digest = Field(
        description="The digest of the request, sources, statements and open questions"
    )
    model: NonBlank = Field(description="The model that wrote the statements")
    prompt_version: VersionTag = Field(description="The version of the prompt it wrote them with")

    def expected_digest(self) -> str:
        """Return the digest this content must carry.

        Returns:
            The digest of the content the reviewer reads.
        """
        return digest_json(self.id_basis())

    def expected_id(self) -> str:
        """Return the id this content must carry.

        Returns:
            ``brief:`` and the first 16 hex characters of the content digest.
        """
        hex_part = self.expected_digest()[len(DIGEST_PREFIX) : len(DIGEST_PREFIX) + ID_HEX_LENGTH]
        return f"{self.ID_PREFIX}:{hex_part}"

    @model_validator(mode="after")
    def _digest_recomputes(self, info: ValidationInfo) -> Self:
        if info.context and info.context.get(DRAFT_CONTEXT_KEY):
            return self
        if self.content_digest != self.expected_digest():
            raise PydanticCustomError(
                "digest.recompute",
                "the content digest {given} does not recompute; the content gives {expected}",
                {"given": self.content_digest, "expected": self.expected_digest()},
            )
        return self

    @classmethod
    def build(cls, *, context: dict[str, Any] | None = None, **fields: Any) -> Self:
        """Build a brief, deriving its content digest and its id.

        Args:
            context: Validation context passed on to the checks.
            **fields: Every field except ``id`` and ``content_digest``.

        Returns:
            The validated brief.

        Raises:
            pydantic.ValidationError: If any field breaks a rule of the record.
        """
        placeholder = DIGEST_PREFIX + "0" * 64
        draft = cls.model_validate(
            {
                **fields,
                "id": f"{cls.ID_PREFIX}:{'0' * ID_HEX_LENGTH}",
                "content_digest": placeholder,
            },
            context={**(context or {}), DRAFT_CONTEXT_KEY: True},
        )
        data = draft.to_json()
        data["content_digest"] = draft.expected_digest()
        data["id"] = draft.expected_id()
        return cls.model_validate(data, context=context)
