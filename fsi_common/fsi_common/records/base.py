"""The base record with its content-derived id, and the field types every record family shares."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Annotated, Any, ClassVar, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from fsi_common.ids import ID_HEX_LENGTH, content_id

DRAFT_CONTEXT_KEY = "fsi_common.draft"
"""Validation context key under which ``build`` validates a record before its id is known."""

NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
"""Text with at least one character that is not white space."""

Snake = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
"""A lower-case name of letters, digits and underscores, for example ``obligation``."""

Anchor = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*:\S+$")]
"""A place in a source in its own identifiers: ``para:7.1``, ``row:FIRM-001``, ``tx:TX-1003``."""

Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
"""A SHA-256 digest written as ``sha256:`` and 64 lower-case hex characters."""

VersionTag = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")]
"""A version label such as ``1.0.0`` or ``v2``."""

AnyRecordId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]*:[0-9a-f]{16}$")]
"""The id of any record: its family, a colon and 16 hex characters."""


def record_id(prefix: str) -> Any:
    """Return the field type of an id of one record family.

    Args:
        prefix: The family, for example ``fact``.

    Returns:
        An annotated string type whose pattern admits only ids of that family.
    """
    return Annotated[str, StringConstraints(pattern=rf"^{prefix}:[0-9a-f]{{{ID_HEX_LENGTH}}}$")]


SourceId = record_id("source")
UnitId = record_id("unit")
FactId = record_id("fact")
QuestionId = record_id("question")
DisagreementId = record_id("disagreement")
DecisionId = record_id("decision")
StatementId = record_id("statement")
BriefId = record_id("brief")
SignOffId = record_id("signoff")
AccountingId = record_id("accounting")


def _real_date(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise PydanticCustomError(
            "schema.date", "{value} is not a calendar date in the form YYYY-MM-DD", {"value": value}
        ) from exc
    return value


IsoDate = Annotated[
    str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$"), AfterValidator(_real_date)
]
"""A calendar date written as ``YYYY-MM-DD``."""

MACHINE_IDENTITIES = (
    "agent",
    "ai",
    "assistant",
    "automated",
    "automation",
    "bot",
    "chatbot",
    "llm",
    "machine",
    "model",
    "system",
)
"""Values that, standing alone as a name or a role, name a program or a service and no person."""

MODEL_PRODUCTS = (
    "anthropic",
    "chatgpt",
    "claude",
    "copilot",
    "fable",
    "gemini",
    "gpt",
    "haiku",
    "llama",
    "mistral",
    "mythos",
    "openai",
    "opus",
    "sonnet",
)
"""Model products and their makers; alone, or followed only by model words and versions, a value
naming one is a model (``claude``, ``GPT``, ``claude-sonnet-5-5``, ``Claude Opus 5.5``)."""

MODEL_WORDS = ("code", "flash", "instant", "mini", "nano", "pro", "turbo", "ultra")
"""Words that follow a product's name in a model's name, as in ``Claude Code`` or ``GPT mini``."""


def _words(words: tuple[str, ...], *, case_free: bool) -> str:
    if not case_free:
        return "|".join(words)
    return "|".join(
        "".join(f"[{c.lower()}{c.upper()}]" if c.isalpha() else re.escape(c) for c in word)
        for word in words
    )


def _machine_pattern(*, case_free: bool) -> str:
    letters = "a-zA-Z" if case_free else "a-z"
    version = rf"\d[{letters}0-9.]*"
    token = rf"(?:{_words(MODEL_PRODUCTS + MODEL_WORDS, case_free=case_free)}|{version})"
    model = (
        rf"(?:{_words(MODEL_PRODUCTS, case_free=case_free)})(?:{version})?"
        rf"(?:[\s_:/-]+{token})*(?:\[1{'[mM]' if case_free else 'm'}\])?"
    )
    return rf"^\s*(?:(?:{_words(MACHINE_IDENTITIES, case_free=case_free)})|{model})\s*$"


MACHINE_PATTERN = re.compile(_machine_pattern(case_free=False), re.IGNORECASE)
"""Matches a whole value, trimmed and in any case, that is a machine identity or a model's name.

A value that only contains such a word is a person's ("Claude Dupont", "Head of Model Risk",
"Compliance Assistant", "Transfer Agent", "AI and Automation Lead"). The control that keeps the
machine from deciding is structural: only the reviewer's application writes a decision.
"""

MACHINE_SCHEMA_PATTERN = _machine_pattern(case_free=True)
"""The same pattern for JSON Schema, whose regular expressions have no case-insensitive flag."""

_PERSON_TEXT_SCHEMA = {"minLength": 1, "pattern": r"\S", "not": {"pattern": MACHINE_SCHEMA_PATTERN}}


class Part(BaseModel):
    """A part of a record: strict types, no unknown fields, immutable once built."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, populate_by_name=True)


class Person(Part):
    """A named person and the role in which they act; never a model, a program or a service."""

    name: str = Field(
        description="The person's name as they give it", json_schema_extra=_PERSON_TEXT_SCHEMA
    )
    role: str = Field(
        description="The role they act in, for example 'Head of Compliance'",
        json_schema_extra=_PERSON_TEXT_SCHEMA,
    )

    @field_validator("name", "role")
    @classmethod
    def _a_person(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise PydanticCustomError(
                "person.empty", "the {field} of the person is empty", {"field": info.field_name}
            )
        if MACHINE_PATTERN.fullmatch(value):
            raise PydanticCustomError(
                "person.machine",
                "the {field} '{value}' is a model, a program or a service; "
                "only a person may decide",
                {"field": info.field_name, "value": value.strip()},
            )
        return value


class SourceRef(Part):
    """A place in one source: the source's id and an anchor in its own identifiers."""

    source_id: SourceId = Field(description="The id of the source record")
    anchor: Anchor = Field(description="The place in the source, for example 'para:7.1'")


class Extractor(Part):
    """The named, versioned code or step that produced a record."""

    name: NonBlank = Field(description="The extractor's name, for example 'paragraph-splitter'")
    version: VersionTag = Field(description="The extractor's version")


class Addressed(Part):
    """A part whose ``id`` is derived from its own content and checked whenever it is read."""

    ID_PREFIX: ClassVar[str] = ""
    ID_EXCLUDES: ClassVar[frozenset[str]] = frozenset({"id", "schema_id"})

    def id_basis(self, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return the fields the id is derived from, as JSON.

        Args:
            context: The validation context; a family whose id depends on a topic's declaration
                (facts) reads it from here.

        Returns:
            The record as JSON without its id, its schema name and any field the family excludes.
        """
        return self.model_dump(mode="json", by_alias=False, exclude=set(self.ID_EXCLUDES))

    def judged_basis(self) -> dict[str, Any]:
        """Return what a person judges when they decide on this record, as JSON.

        A decision keeps this beside the digest of the whole record it was shown, so a rerun that
        changes only what was not judged (a model's name, a check's wording) carries the decision.

        Returns:
            The fields the id is derived from; a fact returns its own judged fields.
        """
        return self.id_basis()

    def expected_id(self, context: Mapping[str, Any] | None = None) -> str:
        """Return the id this content must carry.

        Args:
            context: The validation context, passed on to ``id_basis``.

        Returns:
            The content-derived id.
        """
        return content_id(self.ID_PREFIX, self.id_basis(context))

    @model_validator(mode="after")
    def _id_recomputes(self, info: ValidationInfo) -> Self:
        if info.context and info.context.get(DRAFT_CONTEXT_KEY):
            return self
        expected = self.expected_id(info.context)
        given = getattr(self, "id", None)
        if given != expected:
            raise PydanticCustomError(
                "id.recompute",
                "the id {given} does not recompute from the content, which gives {expected}",
                {"given": given, "expected": expected},
            )
        return self

    @classmethod
    def build(cls, *, context: dict[str, Any] | None = None, **fields: Any) -> Self:
        """Build a record from its fields, deriving its id from its content.

        Args:
            context: Validation context passed on to the record's checks (for example a topic's
                closed list of fact kinds).
            **fields: Every field except ``id``.

        Returns:
            The validated record with its id.

        Raises:
            pydantic.ValidationError: If any field breaks a rule of the record.
        """
        draft_context = {**(context or {}), DRAFT_CONTEXT_KEY: True}
        placeholder = f"{cls.ID_PREFIX}:{'0' * ID_HEX_LENGTH}"
        draft = cls.model_validate({**fields, "id": placeholder}, context=draft_context)
        data = draft.to_json()
        data["id"] = draft.expected_id(context)
        return cls.model_validate(data, context=context)

    def to_json(self) -> dict[str, Any]:
        """Return the record as the JSON object its schema describes.

        Returns:
            A dict of JSON values with the schema field written as ``schema``.
        """
        return self.model_dump(mode="json", by_alias=True)


class Record(Addressed):
    """A top-level record, with the schema name that tells its type apart in JSON."""

    SCHEMA: ClassVar[str] = ""
