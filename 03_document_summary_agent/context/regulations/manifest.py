"""The record of each regulation the build reads: where it comes from, its digest and its terms."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from context.regulations.errors import RegulationError
from utils.db import DATA_DIR

REGULATIONS_DIR = DATA_DIR / "regulations"
"""The folder that holds the manifest, the sources note and the pinned unit records."""

CACHE_DIR = REGULATIONS_DIR / "cache"
"""Where fetched bytes are kept; the folder holds its own ignore rule and is never committed."""

MANIFEST_FILE = REGULATIONS_DIR / "sources.json"


@dataclass(frozen=True)
class RegulationEntry:
    """One regulation as the manifest records it.

    Attributes:
        key: The key the build uses, for example ``DORA``.
        title: The act's title as its publisher gives it.
        short_name: How the pages name it in running text.
        publisher: The official publisher.
        address: The address the bytes are fetched from.
        request_headers: The headers the publisher's service needs to give the text.
        reader: Which reader reads the bytes, ``official_journal`` or ``supervisory_statement``.
        fetched: The date the bytes were fetched, as ``YYYY-MM-DD``.
        digest: The SHA-256 digest of the bytes fetched, as ``sha256:`` and 64 hex characters.
        size: The size of the bytes fetched.
        cache_file: The name of the file the bytes are cached under.
        terms: The terms of reuse as recorded on the source.
        text_file: For a text held in the repository, its path in ``data/regulations``; empty for a
            text that is fetched.
        notice: For a held text, where to read the terms it is held on: the note that quotes the
            publisher's notice.
        notice_address: The address the publisher's notice was read at.
        notice_passages: The notice's passages that bear on reuse, each as the notice words it.
        notice_omission: What a quotation of the notice leaves out, and where it is recorded.
        attribution: The acknowledgement of the source.
    """

    key: str
    title: str
    short_name: str
    publisher: str
    address: str
    request_headers: dict[str, str]
    reader: str
    fetched: str
    digest: str
    size: int
    cache_file: str
    terms: str
    text_file: str = ""
    notice: str = ""
    notice_address: str = ""
    notice_passages: tuple[str, ...] = ()
    notice_omission: str = ""
    attribution: str = ""


@dataclass(frozen=True)
class OtherVersion:
    """A version of a regulation the build knows of and does not read."""

    key: str
    title: str
    address: str
    fetched: str
    digest: str
    size: int
    status: str


@dataclass(frozen=True)
class Manifest:
    """Every regulation the build reads, and the versions it knows of and does not read."""

    regulations: tuple[RegulationEntry, ...]
    other_versions: tuple[OtherVersion, ...]

    def get(self, key: str) -> RegulationEntry:
        """Return the entry for a regulation key.

        Args:
            key: The key, for example ``AI-ACT``.

        Returns:
            The entry.

        Raises:
            RegulationError: If the manifest has no such regulation.
        """
        for entry in self.regulations:
            if entry.key == key:
                return entry
        known = ", ".join(e.key for e in self.regulations)
        raise RegulationError(f"There is no regulation {key} in the manifest; it holds {known}.")


def load_manifest(path: Path = MANIFEST_FILE) -> Manifest:
    """Load the manifest of regulations.

    Args:
        path: The manifest file.

    Returns:
        The manifest.

    Raises:
        RegulationError: If the file is missing or does not hold the fields an entry needs.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        regulations = tuple(
            RegulationEntry(
                **{
                    **row,
                    "notice_passages": tuple(row.get("notice_passages", ())),
                }
            )
            for row in raw["regulations"]
        )
        others = tuple(OtherVersion(**row) for row in raw["other_versions"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RegulationError(f"The manifest {path} cannot be read: {exc}.") from exc
    return Manifest(regulations=regulations, other_versions=others)
