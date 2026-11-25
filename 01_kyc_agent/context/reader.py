"""Read the applications and the two lists into sources, and each application against each entry."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from context.errors import ApplicationNotFoundError
from fsi_common.ids import digest_bytes, digest_json, digest_text
from fsi_common.records import Source, SourceUnit
from utils import PROJECT_ROOT, db
from utils.db import DATA_DIR
from utils.records import SCREENING_SCHEME, application_anchor

SOURCE_TERMS = (
    "Fictional sample data from the FSI hackathon starter "
    "(github.com/langchain-samples/fsi-hackathon-london-2026), carried with credit"
)
"""The terms recorded for every source this topic reads: the starter's fictional data."""

SCREENING_SOURCE_KEY = "screenings"
APPLICATIONS_KEY = "applications"
LISTS = ("sanctions", "pep")
LIST_FILES = {"sanctions": "sanctions_list", "pep": "pep_list"}


@dataclass(frozen=True)
class ListEntry:
    """One entry of a watchlist, with the line it was read from.

    The starter's lists carry no id, so an entry is named by its list and its line number.
    """

    list: str
    number: int
    name: str
    date_of_birth: str | None
    detail: str
    line: str

    @property
    def anchor_part(self) -> str:
        """The entry's place in the screening anchors, for example ``sanctions-1``."""
        return f"{self.list}-{self.number}"


@dataclass(frozen=True)
class ApplicationsRead:
    """The applications read whole: the source, a unit for each, and each unit's text."""

    source: Source
    units: tuple[SourceUnit, ...]
    unit_text: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ScreeningsRead:
    """Every application against every list entry: the source, a unit for each pair."""

    source: Source
    units: tuple[SourceUnit, ...]
    unit_text: dict[str, str] = field(default_factory=dict)


def screening_anchor(customer_id: str, anchor_part: str) -> str:
    """Return the anchor of the screening of one application against one entry.

    Args:
        customer_id: The customer's id.
        anchor_part: The entry's place, for example ``sanctions-1``.

    Returns:
        ``pair:CUST-003/sanctions-1``.
    """
    return f"{SCREENING_SCHEME}:{customer_id}/{anchor_part}"


def _relative(name: str) -> str:
    path = DATA_DIR / name
    if path.is_relative_to(PROJECT_ROOT.parent):
        return path.relative_to(PROJECT_ROOT.parent).as_posix()
    return path.as_posix()


def entries_of() -> tuple[ListEntry, ...]:
    """Read every entry of both lists, the sanctions list first, in file order.

    Returns:
        The entries, each with the line it came from.
    """
    entries: list[ListEntry] = []
    for list_name in LISTS:
        path = DATA_DIR / f"{LIST_FILES[list_name]}.jsonl"
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
        for number, line in enumerate((ln for ln in lines if ln), 1):
            row = json.loads(line)
            if list_name == "sanctions":
                detail = row["program"]
            else:
                detail = f"{row['position']}, {row['country']}"
            entries.append(
                ListEntry(
                    list=list_name,
                    number=number,
                    name=row["name"],
                    date_of_birth=row.get("date_of_birth"),
                    detail=detail,
                    line=line,
                )
            )
    return tuple(entries)


def _chosen(customer_ids: list[str] | None) -> list[dict]:
    rows = db.table("applications")
    if customer_ids is None:
        return rows
    known = {row["customer_id"] for row in rows}
    missing = sorted(set(customer_ids) - known)
    if missing:
        raise ApplicationNotFoundError(
            f"There is no application for {', '.join(missing)}; the table holds "
            f"{len(known)} applications."
        )
    wanted = set(customer_ids)
    return [row for row in rows if row["customer_id"] in wanted]


def read_applications(customer_ids: list[str] | None = None) -> ApplicationsRead:
    """Read the applications into a source and a unit for each.

    Args:
        customer_ids: The customers to read, in any order; every application when omitted.

    Returns:
        The source, whose digest is of the table's bytes, and a unit for each application in file
        order, whose digest is of the application's text.

    Raises:
        ApplicationNotFoundError: If a customer has no application; every one is named.
    """
    path = DATA_DIR / "applications.jsonl"
    source = Source.build(
        key=APPLICATIONS_KEY,
        title="Account applications",
        kind="table",
        digest=digest_bytes(path.read_bytes()),
        locator=_relative("applications.jsonl"),
        terms=SOURCE_TERMS,
    )
    units, unit_text = [], {}
    for row in _chosen(customer_ids):
        unit = SourceUnit.build(
            source_id=source.id,
            anchor=application_anchor(row["customer_id"]),
            text_digest=digest_text(row["application"]),
        )
        units.append(unit)
        unit_text[unit.id] = row["application"]
    return ApplicationsRead(source=source, units=tuple(units), unit_text=unit_text)


def read_screenings(customer_ids: list[str] | None = None) -> ScreeningsRead:
    """Read every chosen application set against every list entry, as one unit for each pair.

    Args:
        customer_ids: The customers to read; every application when omitted.

    Returns:
        The source, whose digest is of the three files it is made from, and a unit for each pair.
        The unit's text is the application, a line break and the entry's line, each labelled.

    Raises:
        ApplicationNotFoundError: If a customer has no application.
    """
    files = {
        "applications": DATA_DIR / "applications.jsonl",
        "sanctions_list": DATA_DIR / "sanctions_list.jsonl",
        "pep_list": DATA_DIR / "pep_list.jsonl",
    }
    source = Source.build(
        key=SCREENING_SOURCE_KEY,
        title="Each application set against each watchlist entry",
        kind="screening",
        digest=digest_json({name: digest_bytes(p.read_bytes()) for name, p in files.items()}),
        locator=", ".join(_relative(p.name) for p in files.values()),
        terms=SOURCE_TERMS,
    )
    entries = entries_of()
    units, unit_text = [], {}
    for row in _chosen(customer_ids):
        for entry in entries:
            text = (
                f"Application {row['customer_id']}: {row['application']}\n"
                f"List entry {entry.anchor_part}: {entry.line}"
            )
            unit = SourceUnit.build(
                source_id=source.id,
                anchor=screening_anchor(row["customer_id"], entry.anchor_part),
                text_digest=digest_text(text),
            )
            units.append(unit)
            unit_text[unit.id] = text
    return ScreeningsRead(source=source, units=tuple(units), unit_text=unit_text)
