"""Read the firm and provider tables into sources, one unit per row and attribute facts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from context.checks import check_quote
from context.errors import FirmNotFoundError
from context.reader import SOURCE_TERMS, relative_locator
from fsi_common.ids import digest_bytes, digest_text
from fsi_common.records import Extractor, Fact, Source, SourceUnit
from utils import db
from utils.db import DATA_DIR
from utils.records import FACT_CONTEXT

TABLE_READER = Extractor(name="table-reader", version="0.1.0")
"""The step that turns a table row into facts; code, so its facts name no model."""

FIRM_FIELDS = (
    "name",
    "type",
    "customers",
    "total_assets",
    "operational_resilience_senior_manager",
    "notes",
)
PROVIDER_FIELDS = ("name", "service")
_OBJECT = re.compile(r"\{[^{}]*\}")


@dataclass(frozen=True)
class TablesRead:
    """The two tables read whole: sources, row units, unit texts and the facts read from rows."""

    sources: tuple[Source, ...]
    units: tuple[SourceUnit, ...]
    unit_text: dict[str, str]
    facts: tuple[Fact, ...]


def _read_table(
    name: str, title: str, key_field: str
) -> tuple[Source, list[SourceUnit], dict[str, str], dict[str, str]]:
    path = DATA_DIR / f"{name}.jsonl"
    source = Source.build(
        key=name,
        title=title,
        kind="table",
        digest=digest_bytes(path.read_bytes()),
        locator=relative_locator(f"{name}.jsonl"),
        terms=SOURCE_TERMS,
    )
    units, unit_text, lines = [], {}, {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row_key = json.loads(line)[key_field]
        text = line.strip()
        unit = SourceUnit.build(
            source_id=source.id, anchor=f"row:{row_key}", text_digest=digest_text(text)
        )
        units.append(unit)
        unit_text[unit.id] = text
        lines[row_key] = text
    return source, units, unit_text, lines


def _fact(
    kind: str, source: Source, unit: SourceUnit, text: str, quote: str, attributes: dict[str, Any]
) -> Fact:
    anchor = unit.anchor
    return Fact.build(
        context=FACT_CONTEXT,
        kind=kind,
        subject={"source_id": source.id, "anchor": anchor},
        quote=quote,
        attributes=attributes,
        status={"status": "documented"},
        provenance={
            "source_id": source.id,
            "anchor": anchor,
            "extractor": TABLE_READER,
            "as_of": source.digest,
        },
        checks=[check_quote(quote, text, anchor=anchor)],
    )


def _field_quote(field: str, value: Any) -> str:
    return f'"{field}": {json.dumps(value, ensure_ascii=False)}'


def _link_quote(text: str, link: dict[str, Any]) -> str:
    for found in _OBJECT.findall(text):
        if json.loads(found) == link:
            return found
    return _field_quote("provider_id", link["provider_id"])


def read_tables(firm_id: str) -> TablesRead:
    """Read the firm table and the provider table, every row, into units and facts.

    Each field of a firm row is a ``firm_attribute`` fact, each provider link in it another one,
    and each field of a provider row a ``provider_attribute`` fact. A quote is the field as the row
    writes it, and the quote check runs on every fact.

    Args:
        firm_id: The firm the run is for; the table must hold its row.

    Returns:
        The two sources, a unit for every row, and the facts of every row.

    Raises:
        FirmNotFoundError: If the firm table has no row for the firm.
    """
    firms, firm_units, firm_text, firm_lines = _read_table("firms", "Firm profiles", "firm_id")
    providers, provider_units, provider_text, provider_lines = _read_table(
        "third_party_providers", "Third-party providers", "provider_id"
    )
    if db.get("firms", firm_id=firm_id) is None:
        raise FirmNotFoundError(f"There is no firm {firm_id} in the firm table.")
    facts: list[Fact] = []
    for unit in firm_units:
        row_key = unit.anchor.partition(":")[2]
        row, text = db.get("firms", firm_id=row_key), firm_lines[row_key]
        for field in FIRM_FIELDS:
            attributes = {"field": field, "value": row[field]}
            facts.append(
                _fact(
                    "firm_attribute", firms, unit, text, _field_quote(field, row[field]), attributes
                )
            )
        for link in row["providers"]:
            attributes = {
                "field": "provider_link",
                "provider_id": link["provider_id"],
                "contract_end": link["contract_end"],
                "material": link["material"],
            }
            facts.append(
                _fact("firm_attribute", firms, unit, text, _link_quote(text, link), attributes)
            )
    for unit in provider_units:
        row_key = unit.anchor.partition(":")[2]
        row, text = db.get("third_party_providers", provider_id=row_key), provider_lines[row_key]
        for field in PROVIDER_FIELDS:
            attributes = {"field": field, "value": row[field]}
            facts.append(
                _fact(
                    "provider_attribute",
                    providers,
                    unit,
                    text,
                    _field_quote(field, row[field]),
                    attributes,
                )
            )
    return TablesRead(
        sources=(firms, providers),
        units=tuple(firm_units + provider_units),
        unit_text={**firm_text, **provider_text},
        facts=tuple(facts),
    )
