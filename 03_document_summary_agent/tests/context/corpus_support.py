"""Helpers for the corpus tests: build a corpus folder in a temporary place, file by file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fsi_common.ids import digest_bytes

WRITTEN_TERMS = (
    "Fictional sample data written for this repository; reuse it under the repository's terms"
)


def written_entry(doc_id: str, file: str, data: bytes, **changes: Any) -> dict[str, Any]:
    """Return a manifest entry for a document we wrote, with the digest of its bytes.

    Args:
        doc_id: The document's id.
        file: The file name inside the corpus folder.
        data: The file's bytes, whose digest the entry records.
        **changes: Fields to set or replace in the entry.

    Returns:
        The entry as a JSON object.
    """
    entry = {
        "id": doc_id,
        "title": f"Title of {doc_id}",
        "file": file,
        "format": "markdown",
        "language": "en",
        "holding": "committed",
        "source": "Written for this repository as fictional sample data",
        "date": "2026-11-25",
        "date_kind": "written",
        "digest": digest_bytes(data),
        "terms": WRITTEN_TERMS,
        "terms_address": None,
    }
    entry.update(changes)
    return entry


def published_entry(doc_id: str, file: str, data: bytes, **changes: Any) -> dict[str, Any]:
    """Return a manifest entry for a published document that the corpus does not hold.

    Args:
        doc_id: The document's id.
        file: The file name the fetched copy is kept under.
        data: The bytes the publisher serves, whose digest the entry records.
        **changes: Fields to set or replace in the entry.

    Returns:
        The entry as a JSON object.
    """
    entry = {
        "id": doc_id,
        "title": f"Title of {doc_id}",
        "file": file,
        "format": "pdf",
        "language": "en",
        "holding": "fetch",
        "source": f"https://example.org/{file}",
        "date": "2026-11-25",
        "date_kind": "fetched",
        "digest": digest_bytes(data),
        "terms": "Reuse is allowed for information only; republication needs permission",
        "terms_address": "https://example.org/legal",
    }
    entry.update(changes)
    return entry


def make_corpus(
    root: Path,
    name: str,
    files: dict[str, bytes],
    documents: list[dict[str, Any]],
    *,
    origin: str = "written",
    manifest_text: str | None = None,
    **changes: Any,
) -> Path:
    """Write a corpus folder with its files and its manifest.

    Args:
        root: The folder that holds corpora.
        name: The corpus folder's name.
        files: Each file's path inside the folder and its bytes.
        documents: The manifest's document entries.
        origin: ``written`` or ``published``.
        manifest_text: Raw text to write as the manifest instead of the JSON built here.
        **changes: Corpus fields to set or replace.

    Returns:
        The corpus folder.
    """
    folder = root / name
    folder.mkdir(parents=True)
    for path, data in files.items():
        target = folder / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {
        "corpus": name,
        "institution": "Example Institution",
        "origin": origin,
        "description": "A corpus made for a test",
        "documents": documents,
    }
    manifest.update(changes)
    text = manifest_text if manifest_text is not None else json.dumps(manifest, indent=2)
    (folder / "manifest.json").write_text(text, encoding="utf-8")
    return folder
