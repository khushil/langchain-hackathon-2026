"""The parts every page is made of: an answer sentence with its tiles, and tables that sort."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

Status = Literal["normal", "needs_person", "failed"]
MAX_TILES = 3
STATUS_WORDS = {"needs_person": "Needs a person", "failed": "Failed"}
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class Tile:
    """One headline figure of a page; with an address, the tile is a link to what it counts."""

    label: str
    value: str
    status: Status = "normal"
    title: str = ""
    href: str | None = None


@dataclass(frozen=True)
class Answer:
    """A page's answer: one sentence and at most three tiles, built together from one object."""

    sentence: str
    tiles: tuple[Tile, ...] = ()

    def __post_init__(self) -> None:
        if len(self.tiles) > MAX_TILES:
            raise ValueError(
                f"A page's answer has at most {MAX_TILES} tiles, not {len(self.tiles)}."
            )


@dataclass(frozen=True)
class Cell:
    """One table cell: its text, the status it shows, and where it leads."""

    text: str
    status: Status = "normal"
    href: str | None = None
    title: str | None = None
    sort_value: str | None = None


@dataclass(frozen=True)
class Column:
    """One table column."""

    key: str
    label: str


@dataclass(frozen=True)
class HeaderLink:
    """A column heading with the address that sorts by it."""

    label: str
    href: str
    sorted_as: Literal["ascending", "descending", "none"]


@dataclass(frozen=True)
class TableView:
    """A table ready to draw: headings, rows in sort order, and the export address."""

    columns: tuple[Column, ...]
    headers: tuple[HeaderLink, ...]
    rows: tuple[dict[str, Cell], ...]
    export_href: str
    caption: str
    empty: str = ""
    extra: dict[str, str] = field(default_factory=dict)


def natural_key(text: str) -> tuple[tuple[int, int | str], ...]:
    """Return a key that orders ``7.2`` before ``7.10`` and ``2`` before ``10``.

    Args:
        text: The text to order.

    Returns:
        A key comparing digit runs as numbers and the rest as lower-case text.
    """
    parts = re.split(r"(\d+)", text.lower())
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts if p != "")


def sort_rows(
    rows: Sequence[dict[str, Cell]], key: str | None, *, descending: bool = False
) -> list[dict[str, Cell]]:
    """Sort table rows by one column, keeping their order when the key is unknown.

    Args:
        rows: The rows.
        key: The column key to sort by; None keeps the order given.
        descending: Whether to reverse the order.

    Returns:
        The rows in the new order; the sort is stable.
    """
    if key is None or any(key not in row for row in rows):
        return list(rows)

    def order(row: dict[str, Cell]) -> tuple[tuple[int, int | str], ...]:
        cell = row[key]
        return natural_key(cell.sort_value if cell.sort_value is not None else cell.text)

    return sorted(rows, key=order, reverse=descending)


def build_table(
    columns: Sequence[Column],
    rows: Sequence[dict[str, Cell]],
    *,
    sort: str | None,
    descending: bool,
    href_for: Callable[..., str],
    export_href: str,
    caption: str,
    empty: str = "",
) -> TableView:
    """Make a table view from rows, with its sort links and export address.

    Args:
        columns: The columns, in order.
        rows: The rows, as cells by column key.
        sort: The column to sort by, or None.
        descending: Whether the sort runs down.
        href_for: Returns the page's address with ``sort`` and ``dir`` set to given values.
        export_href: The address of the CSV of the same rows in the same order.
        caption: What the table lists.
        empty: What to say when there are no rows.

    Returns:
        The table.
    """
    valid = sort if sort in {c.key for c in columns} else None
    headers = []
    for column in columns:
        here = valid == column.key
        headers.append(
            HeaderLink(
                label=column.label,
                href=href_for(sort=column.key, dir="desc" if here and not descending else "asc"),
                sorted_as=("descending" if descending else "ascending") if here else "none",
            )
        )
    return TableView(
        columns=tuple(columns),
        headers=tuple(headers),
        rows=tuple(sort_rows(rows, valid, descending=descending)),
        export_href=export_href,
        caption=caption,
        empty=empty,
    )


def table_csv(view: TableView) -> str:
    """Write a table's rows as CSV, headings first, in the order shown.

    Cells that a spreadsheet would read as a formula are written as text.

    Args:
        view: The table as drawn.

    Returns:
        The CSV text.
    """
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([c.label for c in view.columns])
    for row in view.rows:
        writer.writerow([_safe(row[c.key].text) for c in view.columns])
    return out.getvalue()


def _safe(text: str) -> str:
    return "'" + text if text.startswith(_FORMULA_START) else text
