"""Read a customer's stream into sources, one unit for each transaction and one for the customer."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from context.errors import CustomerNotFoundError, EmptyStreamError
from fsi_common.ids import digest_bytes, digest_text
from fsi_common.records import Source, SourceUnit
from utils import PROJECT_ROOT, db
from utils.db import DATA_DIR
from utils.records import customer_anchor, transaction_anchor
from utils.transaction_processing import transaction_stream

SOURCE_TERMS = (
    "Fictional sample data from the FSI hackathon starter "
    "(github.com/langchain-samples/fsi-hackathon-london-2026), carried with credit"
)
"""The terms recorded for every source this topic reads: the starter's fictional data."""


@dataclass(frozen=True)
class StreamRead:
    """A customer's stream as read: the two sources, a unit for each row and the rows themselves.

    ``transactions`` are the rows of the window in time order. ``unit_text`` holds each unit's
    line of its file by unit id; a unit's digest is of that line.
    """

    user_id: str
    window: tuple[str | None, str | None]
    sources: tuple[Source, Source]
    units: tuple[SourceUnit, ...]
    unit_text: dict[str, str]
    transactions: tuple[dict, ...]
    profile: dict
    unit_of: dict[str, SourceUnit] = field(default_factory=dict)

    @property
    def transaction_source(self) -> Source:
        """The source the transactions were read from."""
        return self.sources[0]

    @property
    def profile_source(self) -> Source:
        """The source the customer's profile was read from."""
        return self.sources[1]


def relative_locator(path_in_data: str) -> str:
    """Return a data file's path relative to the repository root.

    Args:
        path_in_data: The path inside the topic's ``data`` folder.

    Returns:
        The path from the repository root, for example
        ``02_transaction_monitoring_agent/data/transactions.jsonl``.
    """
    return (DATA_DIR / path_in_data).relative_to(PROJECT_ROOT.parent).as_posix()


def _source(name: str, title: str) -> Source:
    path = DATA_DIR / f"{name}.jsonl"
    return Source.build(
        key=name,
        title=title,
        kind="table",
        digest=digest_bytes(path.read_bytes()),
        locator=relative_locator(f"{name}.jsonl"),
        terms=SOURCE_TERMS,
    )


def _line_of(name: str, key_field: str, key: str) -> str:
    path = DATA_DIR / f"{name}.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and json.loads(line)[key_field] == key:
            return line.strip()
    raise LookupError(f"{name}.jsonl has no row with {key_field} {key}")


def read_stream(user_id: str, *, start: str | None = None, end: str | None = None) -> StreamRead:
    """Read one customer's transactions in a window, and the customer's profile row.

    The window runs from ``start`` up to, and not including, ``end``, as the starter's
    ``transaction_stream`` has it; with neither, the customer's whole stream is read.

    Args:
        user_id: The customer, for example ``USR-001``.
        start: The first timestamp to read, as the data writes it, or None for the beginning.
        end: The timestamp to stop before, or None for the end.

    Returns:
        The stream read: sources, units, unit texts and the rows.

    Raises:
        CustomerNotFoundError: If the profile table has no row for the customer.
        EmptyStreamError: If the customer has no transaction in the window.
    """
    profile = db.get("customer_profiles", user_id=user_id)
    if profile is None:
        raise CustomerNotFoundError(f"There is no customer {user_id} in the profile table.")
    rows = transaction_stream(user_id, start, end)
    if not rows:
        raise EmptyStreamError(
            f"{user_id} has no transaction from {start or 'the start'} to {end or 'the end'}."
        )
    transactions = _source("transactions", "Card transactions")
    profiles = _source("customer_profiles", "Customer profiles")
    units, unit_text, unit_of = [], {}, {}
    for row in rows:
        text = _line_of("transactions", "transaction_id", row["transaction_id"])
        unit = SourceUnit.build(
            source_id=transactions.id,
            anchor=transaction_anchor(row["transaction_id"]),
            text_digest=digest_text(text),
        )
        units.append(unit)
        unit_text[unit.id] = text
        unit_of[unit.anchor] = unit
    text = _line_of("customer_profiles", "user_id", user_id)
    unit = SourceUnit.build(
        source_id=profiles.id, anchor=customer_anchor(user_id), text_digest=digest_text(text)
    )
    units.append(unit)
    unit_text[unit.id] = text
    unit_of[unit.anchor] = unit
    return StreamRead(
        user_id=user_id,
        window=(start, end),
        sources=(transactions, profiles),
        units=tuple(units),
        unit_text=unit_text,
        transactions=tuple(rows),
        profile=profile,
        unit_of=unit_of,
    )
