"""Sources, the units they are read into, and the accounting that shows each unit was dealt with."""

from __future__ import annotations

from typing import ClassVar, Literal, Self

from pydantic import Field, StrictInt, model_validator
from pydantic_core import PydanticCustomError

from fsi_common.records.base import (
    AccountingId,
    Anchor,
    Digest,
    NonBlank,
    Part,
    Record,
    Snake,
    SourceId,
    UnitId,
)


class Source(Record):
    """One thing that was read: a document, a table, an application or a transaction stream.

    The id is derived from the kind, the source's own key and the digest of its bytes, so a
    changed file is a different source and the same bytes always give the same id.
    """

    SCHEMA: ClassVar[str] = "source.v1"
    ID_PREFIX: ClassVar[str] = "source"

    schema_id: Literal["source.v1"] = Field(default="source.v1", alias="schema")
    id: SourceId
    key: NonBlank = Field(
        description="The source's own identifier, for example 'PS26-4' or 'FIRM-001'"
    )
    title: NonBlank = Field(description="The source's title as it gives it")
    kind: Snake = Field(description="What sort of source it is, for example 'document' or 'table'")
    digest: Digest = Field(description="The digest of the source's bytes as read")
    locator: NonBlank = Field(
        description="Where the source was read from: a path in this repository or a URL"
    )
    terms: NonBlank = Field(description="The terms on which the source may be reused, as recorded")

    def id_basis(self) -> dict[str, str]:
        """Return the fields the id is derived from.

        Returns:
            The kind, the key and the digest.
        """
        return {"kind": self.kind, "key": self.key, "digest": self.digest}


class SourceUnit(Record):
    """One unit of a source, named by an anchor in the source's own identifiers.

    A unit is the smallest place a fact can cite: a paragraph of a document, a row of a table, a
    field of an application, a transaction of a stream.
    """

    SCHEMA: ClassVar[str] = "source_unit.v1"
    ID_PREFIX: ClassVar[str] = "unit"

    schema_id: Literal["source_unit.v1"] = Field(default="source_unit.v1", alias="schema")
    id: UnitId
    source_id: SourceId = Field(description="The id of the source the unit belongs to")
    anchor: Anchor = Field(description="The unit's place in its source, for example 'para:7.1'")
    text_digest: Digest = Field(description="The digest of the unit's text as the reader split it")


class UnitWithoutFacts(Part):
    """A unit that produced no fact, with the reason recorded."""

    anchor: Anchor = Field(description="The unit's anchor")
    reason: NonBlank = Field(description="Why the unit holds no fact, in plain words")


class UnitAccounting(Record):
    """For one source, every unit read and what became of it.

    The counts close: units in equals the units with facts plus the units recorded as having none,
    each with its reason, and no unit is in both lists.
    """

    SCHEMA: ClassVar[str] = "unit_accounting.v1"
    ID_PREFIX: ClassVar[str] = "accounting"

    schema_id: Literal["unit_accounting.v1"] = Field(default="unit_accounting.v1", alias="schema")
    id: AccountingId
    source_id: SourceId = Field(description="The id of the source accounted for")
    units_in: StrictInt = Field(ge=0, description="The number of units the source was read into")
    with_facts: list[Anchor] = Field(
        description="The anchors of the units that produced at least one fact"
    )
    without_facts: list[UnitWithoutFacts] = Field(
        description="The units that produced no fact, each with its reason"
    )

    @model_validator(mode="after")
    def _counts_close(self) -> Self:
        without = [unit.anchor for unit in self.without_facts]
        if self.units_in == 0:
            raise PydanticCustomError(
                "accounting.empty",
                "source {source} was read into no units",
                {"source": self.source_id},
            )
        repeated = sorted(
            {a for a in self.with_facts + without if (self.with_facts + without).count(a) > 1}
        )
        if repeated:
            raise PydanticCustomError(
                "accounting.closes",
                "units listed more than once, or both with and without facts: {anchors}",
                {"anchors": ", ".join(repeated)},
            )
        if len(self.with_facts) + len(without) != self.units_in:
            raise PydanticCustomError(
                "accounting.closes",
                "the counts do not close: {units_in} units in, {with_facts} with facts and "
                "{without} without",
                {
                    "units_in": self.units_in,
                    "with_facts": len(self.with_facts),
                    "without": len(without),
                },
            )
        return self
