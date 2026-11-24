"""Facts: one cited statement about one source unit, with its status, provenance and checks."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, Self

from pydantic import Field, StrictBool, StrictInt, StrictStr, ValidationInfo, model_validator
from pydantic_core import PydanticCustomError

from fsi_common.records.base import (
    Anchor,
    Digest,
    Extractor,
    FactId,
    IsoDate,
    NonBlank,
    Part,
    Record,
    Snake,
    SourceId,
    SourceRef,
    VersionTag,
)

FACT_KINDS_CONTEXT_KEY = "fsi_common.fact_kinds"
"""Validation context key holding the topic's closed list of fact kinds."""

AttributeValue = StrictStr | StrictInt | StrictBool | None | list[StrictStr]
"""A normalised attribute value: text, a whole number, a flag, none, or a list of texts."""


class MatchRate(Part):
    """How often an inference rule held, measured over its whole population."""

    matched: StrictInt = Field(ge=0, description="Cases where the rule gave the right answer")
    population: StrictInt = Field(ge=1, description="Every case the rule was measured on")

    @model_validator(mode="after")
    def _within_population(self) -> Self:
        if self.matched > self.population:
            raise PydanticCustomError(
                "status.match-rate",
                "the rule matched {matched} of a population of {population}",
                {"matched": self.matched, "population": self.population},
            )
        return self


class InferenceRule(Part):
    """The named rule an inferred claim rests on."""

    id: NonBlank = Field(description="The rule's name")
    version: VersionTag = Field(description="The rule's version")
    statement: NonBlank = Field(description="What the rule infers from what, in plain words")
    match_rate: MatchRate = Field(description="The rule's measured match rate")


class ClaimStatus(Part):
    """How a fact is known: stated, observed, inferred by a named rule, or not known."""

    status: Literal["documented", "observed", "inferred", "unknown"] = Field(
        description="documented: the source says it; observed: seen in a running system on a "
        "recorded date; inferred: derived by a named rule; unknown: not settled by the sources"
    )
    observed_at: IsoDate | None = Field(
        default=None, description="For observed: the date it was read"
    )
    rule: InferenceRule | None = Field(
        default=None, description="For inferred: the rule it rests on"
    )
    unknown_reason: NonBlank | None = Field(
        default=None, description="For unknown: what was looked for and why it is not known"
    )

    @model_validator(mode="after")
    def _fields_match_status(self) -> Self:
        needs = {"observed": "observed_at", "inferred": "rule", "unknown": "unknown_reason"}
        for status, field in needs.items():
            present = getattr(self, field) is not None
            if status == self.status and not present:
                raise PydanticCustomError(
                    f"status.{status}",
                    "a claim with status {status} needs {field}",
                    {"status": status, "field": field},
                )
            if status != self.status and present:
                raise PydanticCustomError(
                    "status.extra",
                    "a claim with status {status} cannot carry {field}",
                    {"status": self.status, "field": field},
                )
        return self


class Provenance(Part):
    """Where a fact came from and what produced it."""

    source_id: SourceId = Field(description="The source read")
    anchor: Anchor = Field(description="The unit read")
    extractor: Extractor = Field(description="The code or step that produced the fact")
    model: NonBlank | None = Field(default=None, description="The model, where a model produced it")
    prompt_version: VersionTag | None = Field(
        default=None, description="The version of the prompt, where a model produced it"
    )
    as_of: Digest = Field(description="The digest of the source as it was when read")

    @model_validator(mode="after")
    def _model_and_prompt_together(self) -> Self:
        if (self.model is None) != (self.prompt_version is None):
            raise PydanticCustomError(
                "provenance.model-pair",
                "a fact a model produced names both the model and the prompt version; "
                "a fact code produced names neither",
            )
        return self


class CheckResult(Part):
    """The result of one plain-code check run on a fact, such as the quote being word for word."""

    check: NonBlank = Field(
        description="The check's name and version, for example 'quote-verbatim.v1'"
    )
    outcome: Literal["pass", "fail"] = Field(description="Whether the fact passed the check")
    detail: NonBlank = Field(description="What the check compared and what it found")


class Fact(Record):
    """One thing a source says about one of its units, quoted word for word and checked by code.

    ``kind`` comes from the closed list a topic supplies; ``fsi_common`` holds no list of its own.
    The id is derived from the kind, the subject, the quote and the attributes, so a rerun that
    finds the same thing gives the same id whatever produced it.
    """

    SCHEMA: ClassVar[str] = "fact.v1"
    ID_PREFIX: ClassVar[str] = "fact"
    ID_EXCLUDES: ClassVar[frozenset[str]] = frozenset(
        {"id", "schema_id", "status", "provenance", "checks"}
    )

    schema_id: Literal["fact.v1"] = Field(default="fact.v1", alias="schema")
    id: FactId
    kind: Snake = Field(description="The kind of fact, from the topic's closed list")
    subject: SourceRef = Field(description="The source unit the fact is about")
    quote: NonBlank = Field(description="Text copied word for word from the subject unit")
    attributes: dict[Snake, AttributeValue] = Field(
        description="The fact's normalised attributes, for example a requirement and a deadline "
        "as written"
    )
    status: ClaimStatus = Field(description="How the fact is known")
    provenance: Provenance = Field(description="Where the fact came from")
    checks: list[CheckResult] = Field(
        min_length=1, description="The plain-code checks run on the fact"
    )

    @model_validator(mode="before")
    @classmethod
    def _has_quote(cls, data: Any) -> Any:
        if isinstance(data, dict):
            quote = data.get("quote")
            if not isinstance(quote, str) or not quote.strip():
                raise PydanticCustomError(
                    "fact.quote", "the fact has no quote from its source unit"
                )
        return data

    @model_validator(mode="after")
    def _kind_and_provenance(self, info: ValidationInfo) -> Self:
        kinds = (info.context or {}).get(FACT_KINDS_CONTEXT_KEY)
        if kinds is not None and self.kind not in kinds:
            raise PydanticCustomError(
                "fact.kind",
                "kind '{kind}' is not in the topic's list: {kinds}",
                {"kind": self.kind, "kinds": ", ".join(sorted(kinds))},
            )
        if (self.provenance.source_id, self.provenance.anchor) != (
            self.subject.source_id,
            self.subject.anchor,
        ):
            raise PydanticCustomError(
                "fact.provenance-subject",
                "the provenance names {prov} but the fact is about {subject}",
                {
                    "prov": f"{self.provenance.source_id} {self.provenance.anchor}",
                    "subject": f"{self.subject.source_id} {self.subject.anchor}",
                },
            )
        return self

    @property
    def passed_checks(self) -> bool:
        """Whether every plain-code check on the fact passed."""
        return all(result.outcome == "pass" for result in self.checks)
