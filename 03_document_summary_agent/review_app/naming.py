"""Where a fact comes from, in words: a paragraph, or a row of the firm or provider table.

A reviewer reads the firm's name and its providers' names, never a row's identifier, and reads a
row as a table of field and value, never as the record it is stored as.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from fsi_common.records import Fact
from review_app.library import Library
from review_app.source_view import (
    NONE_NAMED,
    anchor_label,
    attribute_label,
    attribute_rows,
    attribute_value,
    kind_label,
)

ROW_SCHEME = "row"
FIRM_PREFIX = "FIRM-"
PROVIDER_PREFIX = "PROVIDER-"
CODE_KEYS = ("firm_id", "provider_id")
"""The row's own identifiers, which the row table leaves out because they are codes, not words."""
LINK_FIELD = "provider_link"
FIELD_WORDS = {LINK_FIELD: "link to a provider"}
UNKNOWN_FIRM = "A firm"
UNKNOWN_PROVIDER = "A provider"


@dataclass(frozen=True)
class RowLine:
    """One line of a row's value, marked when it is what the fact quotes."""

    text: str
    marked: bool


@dataclass(frozen=True)
class RowField:
    """One field of a table row, as a label and the lines of its value."""

    label: str
    lines: tuple[RowLine, ...]


def field_words(field: str) -> str:
    """Write a table's field name in words: ``total_assets`` becomes ``total assets``."""
    return FIELD_WORDS.get(field, field.replace("_", " "))


@dataclass(frozen=True)
class Naming:
    """The names of the firms and providers, which say where a fact from a table row comes from."""

    firms: Mapping[str, str]
    providers: Mapping[str, str]

    @classmethod
    def of(cls, library: Library) -> Naming:
        """Take the names from the library."""
        return cls(firms=library.firms, providers=library.providers)

    def provider(self, provider_id: str) -> str:
        """Return a provider's name; a provider the library lacks is not named by its code."""
        return self.providers.get(provider_id, UNKNOWN_PROVIDER)

    def place(self, anchor: str) -> str:
        """Name a place in a source in words.

        Args:
            anchor: The anchor, such as ``para:7.1`` or ``row:FIRM-001``.

        Returns:
            ``Paragraph 7.1``, ``Harbour Mutual Bank, firm profile`` or ``NimbusCloud, provider``.
        """
        scheme, _, key = anchor.partition(":")
        if scheme != ROW_SCHEME:
            return anchor_label(anchor)
        if key.startswith(PROVIDER_PREFIX):
            return f"{self.provider(key)}, provider"
        return f"{self.firms.get(key, UNKNOWN_FIRM)}, firm profile"

    def fact_name(self, fact: Fact) -> str:
        """Name a fact by where it comes from and what it says.

        Args:
            fact: The fact.

        Returns:
            For a paragraph, ``Paragraph 7.1, obligation``; for a row of a table, such as
            ``Harbour Mutual Bank, firm profile: total assets``.
        """
        anchor = fact.subject.anchor
        if not anchor.startswith(f"{ROW_SCHEME}:"):
            return f"{anchor_label(anchor)}, {kind_label(fact.kind).lower()}"
        field = str(fact.attributes.get("field", kind_label(fact.kind).lower()))
        if field == LINK_FIELD:
            topic = f"link to {self.provider(str(fact.attributes.get('provider_id', '')))}"
        else:
            topic = field_words(field)
        return f"{self.place(anchor)}: {topic}"

    def source_name(self, fact: Fact) -> str:
        """Name where a fact comes from, for a table column: ``Paragraph 7.1``, or a row's name."""
        if fact.subject.anchor.startswith(f"{ROW_SCHEME}:"):
            return self.fact_name(fact)
        return self.place(fact.subject.anchor)

    def profile_line(self, fact: Fact) -> tuple[str, str]:
        """Say what a firm or provider fact states, as an attribute and its value in words.

        Args:
            fact: A fact of the firm profile.

        Returns:
            For example ``("Total assets", "£9 billion")``, or ``("Provider", "NimbusCloud,
            contract ends 30 June 2027, material")`` for a link to a provider.
        """
        held = fact.attributes
        field = str(held.get("field", ""))
        if field == LINK_FIELD:
            return "Provider", self.link_words(held)
        return attribute_label(field), attribute_value(held.get("value"), missing=NONE_NAMED)

    def place_of(self, cited: object) -> str:
        """Name a cited fact, for a link."""
        return self.fact_name(cited.fact)  # type: ignore[attr-defined]

    def attribute_rows(self, fact: Fact) -> list[tuple[str, str]]:
        """Return a fact's attributes as label and value pairs in words.

        Args:
            fact: The fact.

        Returns:
            For a paragraph, its requirements, deadline and the rest; for a table row, the field
            and its value, or the provider, contract end and materiality of a link.
        """
        if not fact.attributes or not fact.subject.anchor.startswith(f"{ROW_SCHEME}:"):
            return attribute_rows(fact)
        held = dict(fact.attributes)
        rows = [("Field", field_words(str(held.pop("field", ""))))]
        if "value" in held:
            rows.append(("Value", attribute_value(held.pop("value"), missing=NONE_NAMED)))
        if "provider_id" in held:
            rows.append(
                (attribute_label("provider_id"), self.provider(str(held.pop("provider_id"))))
            )
        rows += [
            (attribute_label(key), attribute_value(held[key], missing=NONE_NAMED))
            for key in ("contract_end", "material")
            if key in held
        ]
        return rows

    def row_fields(self, unit_text: str, fact: Fact) -> tuple[RowField, ...] | None:
        """Read a table row into fields in words, marking what the fact quotes.

        Args:
            unit_text: The row as the table holds it, one JSON object.
            fact: The fact the row is opened for.

        Returns:
            The fields in the row's order, without the row's codes; or None when the text is not
            a row.
        """
        try:
            row = json.loads(unit_text)
        except ValueError:
            return None
        if not isinstance(row, dict):
            return None
        quoted = fact.attributes.get("field")
        provider_id = fact.attributes.get("provider_id")
        fields = []
        for key, value in row.items():
            if key in CODE_KEYS:
                continue
            if key == "providers":
                lines = tuple(
                    RowLine(
                        self.link_words(link),
                        marked=quoted == LINK_FIELD and link.get("provider_id") == provider_id,
                    )
                    for link in value or []
                ) or (RowLine(NONE_NAMED, marked=quoted == LINK_FIELD),)
            else:
                lines = (RowLine(attribute_value(value, missing=NONE_NAMED), key == quoted),)
            fields.append(RowField(attribute_label(key), lines))
        return tuple(fields)

    def link_words(self, link: Mapping[str, object]) -> str:
        name = self.provider(str(link.get("provider_id", "")))
        ends = attribute_value(link.get("contract_end"), missing=NONE_NAMED)
        weight = "material" if link.get("material") else "not material"
        return f"{name}, contract ends {ends}, {weight}"
