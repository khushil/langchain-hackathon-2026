"""The document library and the firms the start page offers, read from the topic's data folder."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class LibraryError(RuntimeError):
    """The data folder lacks a file the start page needs."""


@dataclass(frozen=True)
class LibrarySection:
    """One section of a document."""

    number: str
    title: str


@dataclass(frozen=True)
class LibraryDocument:
    """A document in the library with its sections."""

    document_id: str
    title: str
    sections: tuple[LibrarySection, ...]


@dataclass(frozen=True)
class Library:
    """The documents and firms a brief can be asked for."""

    documents: tuple[LibraryDocument, ...]
    firms: dict[str, str]

    def document(self, document_id: str) -> LibraryDocument | None:
        """Return a document by its id, or None."""
        return next((d for d in self.documents if d.document_id == document_id), None)

    def firm_name(self, firm_id: str) -> str:
        """Return a firm's name, or its id when the library does not hold it."""
        return self.firms.get(firm_id, firm_id)

    def document_title(self, document_id: str) -> str:
        """Return a document's title, or its id when the library does not hold it."""
        found = self.document(document_id)
        return found.title if found else document_id


def _lines(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LibraryError(f"The library file {path} cannot be read: {exc}") from exc
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def read_library(data_dir: Path = DATA_DIR) -> Library:
    """Read the documents and firms.

    Args:
        data_dir: The topic's data folder.

    Returns:
        The library.

    Raises:
        LibraryError: If a file is missing or unreadable.
    """
    documents = []
    for row in _lines(data_dir / "documents.jsonl"):
        path = data_dir / "documents" / row["document_file"]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise LibraryError(f"The document file {path} cannot be read: {exc}") from exc
        title = text.splitlines()[0].lstrip("# ").strip()
        sections = tuple(
            LibrarySection(number=m.group(1), title=m.group(2).strip())
            for m in re.finditer(r"^## (\d+)\. (.+)$", text, flags=re.MULTILINE)
        )
        documents.append(LibraryDocument(row["document_id"], title, sections))
    firms = {row["firm_id"]: row["name"] for row in _lines(data_dir / "firms.jsonl")}
    return Library(documents=tuple(documents), firms=firms)
