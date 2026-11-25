"""Read a regulation by its key: fetch or load its bytes, check the digest, read, and close."""

from __future__ import annotations

from pathlib import Path

from context.regulations.accounting import (
    RegulationAccounting,
    account_for_regulation,
    load_pin,
)
from context.regulations.errors import RegulationError
from context.regulations.fetch import Opener, ensure_regulation, urllib_opener
from context.regulations.manifest import RegulationEntry, load_manifest
from context.regulations.model import RegulationRead
from context.regulations.official_journal import read_official_journal
from context.regulations.supervisory_statement import read_supervisory_statement


def read_entry(entry: RegulationEntry, data: bytes) -> RegulationRead:
    """Read the bytes of a manifest entry with the reader the entry names.

    Args:
        entry: The manifest entry.
        data: The bytes, already checked against the entry's digest.

    Returns:
        The regulation read.

    Raises:
        RegulationError: If the entry names a reader that does not exist.
    """
    if entry.reader == "official_journal":
        return read_official_journal(
            data, key=entry.key, title=entry.title, locator=entry.address, terms=entry.terms
        )
    if entry.reader == "supervisory_statement":
        return read_supervisory_statement(
            data, key=entry.key, title=entry.title, locator=entry.address, terms=entry.terms
        )
    raise RegulationError(f"The entry {entry.key} names an unknown reader {entry.reader!r}.")


def read_regulation(
    key: str, *, cache_dir: Path | None = None, opener: Opener = urllib_opener
) -> RegulationRead:
    """Return a regulation read whole, fetching and checking its bytes when not cached.

    Args:
        key: The regulation key, for example ``DORA``.
        cache_dir: The cache folder.
        opener: What fetches; tests give a fake.

    Returns:
        The regulation read.
    """
    entry = load_manifest().get(key)
    return read_entry(entry, ensure_regulation(entry, cache_dir=cache_dir, opener=opener))


def read_and_account(
    key: str, *, cache_dir: Path | None = None, opener: Opener = urllib_opener
) -> tuple[RegulationRead, RegulationAccounting]:
    """Read a regulation and close its units against the pinned record.

    Args:
        key: The regulation key.
        cache_dir: The cache folder.
        opener: What fetches; tests give a fake.

    Returns:
        The regulation read and its accounting.

    Raises:
        RegulationAccountingError: If a unit is missing, extra or changed.
    """
    read = read_regulation(key, cache_dir=cache_dir, opener=opener)
    return read, account_for_regulation(read, load_pin(key))
