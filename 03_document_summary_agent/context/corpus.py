"""Read a corpus: a folder of policy documents and the manifest that accounts for every file.

A committed document is a file in the corpus folder. A fetch-only document is kept outside the
repository, in the folder that the setting the manifest names points at, or else in the corpus's
``fetched/`` folder; either way its digest is checked before it is read. Corpus folders are found
in the topic's ``data/policies`` and in every folder the ``POLICY_CORPORA_PATH`` setting names, so a
corpus whose documents may not be republished can keep even its manifest out of the repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from context.corpus_manifest import (
    ALLOWED_EXTRAS,
    FETCHED,
    MANIFEST,
    CorpusError,
    CorpusManifestError,
    CorpusNotFoundError,
    Manifest,
    ManifestDocument,
    load_manifest,
)
from fsi_common.ids import digest_bytes
from fsi_common.records import Source
from utils import PROJECT_ROOT
from utils.db import DATA_DIR

POLICIES_DIR = DATA_DIR / "policies"
"""The folder of the repository that holds one folder per committed corpus."""

CORPORA_SETTING = "POLICY_CORPORA_PATH"
"""The setting that names further folders of corpora, separated as PATH is."""

SOURCE_KIND = "policy_document"
"""The kind of every source a corpus document is read as."""

__all__ = [
    "CORPORA_SETTING",
    "POLICIES_DIR",
    "SOURCE_KIND",
    "CorpusDigestError",
    "CorpusDocument",
    "CorpusError",
    "CorpusFileError",
    "CorpusManifestError",
    "CorpusNotFoundError",
    "CorpusRead",
    "DocumentNotFetchedError",
    "Manifest",
    "ManifestDocument",
    "corpus_folder",
    "corpus_roots",
    "document_path",
    "documents_folder",
    "list_corpora",
    "load_manifest",
    "read_corpus",
]


class CorpusFileError(CorpusError):
    """A file is listed and missing, or present and unaccounted for, or a folder is absent."""


class CorpusDigestError(CorpusError):
    """A document's bytes, or its text twin's, do not have the digest its manifest entry records."""


class DocumentNotFetchedError(CorpusError):
    """A fetch-only document is not yet in the folder it is read from."""


@dataclass(frozen=True)
class CorpusDocument:
    """One document read: its entry, the path read, its bytes, its text if any, its source."""

    entry: ManifestDocument
    path: Path
    data: bytes
    source: Source
    text_path: Path | None = None
    text: str | None = None


@dataclass(frozen=True)
class CorpusRead:
    """A corpus read whole: its manifest, every document, and the line that states the count."""

    manifest: Manifest
    folder: Path
    documents: tuple[CorpusDocument, ...]
    line: str

    def document(self, doc_id: str) -> CorpusDocument | None:
        """Return a document by its id.

        Args:
            doc_id: The document's id in the manifest.

        Returns:
            The document, or None when the corpus has none by that id.
        """
        return next((d for d in self.documents if d.entry.id == doc_id), None)


def corpus_roots() -> list[Path]:
    """Return the folders corpora are found in: the repository's, then each the setting names.

    Returns:
        ``POLICIES_DIR`` followed by every non-empty entry of ``POLICY_CORPORA_PATH``.
    """
    extra = os.environ.get(CORPORA_SETTING, "")
    return [POLICIES_DIR] + [Path(part) for part in extra.split(os.pathsep) if part.strip()]


def list_corpora(*, root: Path | None = None) -> list[str]:
    """Return the name of every corpus folder that holds a manifest, in name order.

    Args:
        root: One folder to look in; by default every folder of ``corpus_roots``.

    Returns:
        The corpus names; a folder that does not exist adds none.
    """
    names: set[str] = set()
    for folder in [root] if root is not None else corpus_roots():
        if folder.is_dir():
            names |= {p.name for p in folder.iterdir() if p.is_dir() and (p / MANIFEST).is_file()}
    return sorted(names)


def corpus_folder(corpus: str, *, root: Path | None = None) -> Path:
    """Return the folder of a corpus.

    Args:
        corpus: The corpus's name, which is its folder's name.
        root: One folder to look in; by default every folder of ``corpus_roots``.

    Returns:
        The corpus folder.

    Raises:
        CorpusNotFoundError: If the name is not one folder name, no such folder exists, or
            folders of that name exist in two places.
    """
    if PurePosixPath(corpus).name != corpus or corpus in {"", ".", ".."}:
        raise CorpusNotFoundError(f"There is no corpus {corpus}: a corpus name is one folder name.")
    roots = [root] if root is not None else corpus_roots()
    found = [r / corpus for r in roots if (r / corpus).is_dir()]
    if not found:
        raise CorpusNotFoundError(
            f"There is no corpus {corpus} in {', '.join(str(r) for r in roots)}."
        )
    if len(found) > 1:
        raise CorpusNotFoundError(
            f"The corpus {corpus} is in two or more places: {', '.join(str(f) for f in found)}."
        )
    return found[0]


def documents_folder(folder: Path, manifest: Manifest) -> Path:
    """Return the folder a corpus's fetch-only documents are read from and fetched into.

    Args:
        folder: The corpus folder.
        manifest: Its manifest.

    Returns:
        The folder the manifest's setting names when that setting is set, else ``fetched/``.

    Raises:
        CorpusFileError: If the setting is set and names no folder.
    """
    setting = manifest.documents_setting
    named = os.environ.get(setting, "").strip() if setting else ""
    if not named:
        return folder / FETCHED
    path = Path(named)
    if not path.is_dir():
        raise CorpusFileError(f"The setting {setting} names {path}, which is not a folder.")
    return path


def document_path(folder: Path, manifest: Manifest, entry: ManifestDocument) -> Path:
    """Return where a document's bytes are kept.

    Args:
        folder: The corpus folder.
        manifest: Its manifest.
        entry: The document's manifest entry.

    Returns:
        The file in the corpus folder when committed, else in ``documents_folder``.
    """
    if entry.holding == "committed":
        return folder / entry.file
    return documents_folder(folder, manifest) / entry.file


def _locator(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT.parent).as_posix()
    except ValueError:
        return path.as_posix()


def _files_in(folder: Path) -> set[str]:
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


def _accounted_for(folder: Path, manifest: Manifest) -> set[str]:
    expected = set(ALLOWED_EXTRAS)
    for entry in manifest.documents:
        for name in (entry.file, entry.text_file):
            if name is None:
                continue
            path = document_path(folder, manifest, entry).parent / name
            if path.is_relative_to(folder):
                expected.add(path.relative_to(folder).as_posix())
    return expected


def _check_no_stray(corpus: str, folder: Path, manifest: Manifest) -> None:
    stray = sorted(_files_in(folder) - _accounted_for(folder, manifest))
    if not stray:
        return
    listed = {e.file: e.id for e in manifest.documents}
    named = [
        f"{name} (a copy of {listed[PurePosixPath(name).name]}, which is committed as "
        f"{PurePosixPath(name).name})"
        if name.startswith(f"{FETCHED}/") and PurePosixPath(name).name in listed
        else name
        for name in stray
    ]
    raise CorpusFileError(
        f"The corpus {corpus} holds file(s) its manifest does not account for: {', '.join(named)}."
    )


def _read_checked(corpus: str, entry: ManifestDocument, path: Path, digest: str) -> bytes:
    data = path.read_bytes()
    if digest_bytes(data) != digest:
        raise CorpusDigestError(
            f"{entry.id} of {corpus} ({path.name}) has the digest {digest_bytes(data)}, and its "
            f"manifest records {digest}."
        )
    return data


def _missing(corpus: str, manifest: Manifest, entry: ManifestDocument, path: Path) -> CorpusError:
    if entry.holding == "committed":
        return CorpusFileError(
            f"{entry.id} is listed as {path.name} in {corpus}, and that file is missing."
        )
    where = ""
    if manifest.documents_setting:
        where = f", or set {manifest.documents_setting} to the folder that holds it"
    return DocumentNotFetchedError(
        f"{entry.id} of {corpus} is not committed and {path.name} is not in {path.parent}; run "
        f"python -m context.corpus_fetch {corpus} to fetch it from {entry.source}{where}."
    )


def _read_document(
    corpus: str, folder: Path, manifest: Manifest, entry: ManifestDocument
) -> CorpusDocument:
    path = document_path(folder, manifest, entry)
    if not path.is_file():
        raise _missing(corpus, manifest, entry, path)
    data = _read_checked(corpus, entry, path, entry.digest)
    text_path, text = None, None
    if entry.text_file is not None and entry.text_digest is not None:
        text_path = path.parent / entry.text_file
        if not text_path.is_file():
            raise _missing(corpus, manifest, entry, text_path)
        text = _read_checked(corpus, entry, text_path, entry.text_digest).decode("utf-8")
    elif entry.format in ("markdown", "text"):
        text_path, text = path, data.decode("utf-8")
    terms = entry.terms if entry.terms_address is None else f"{entry.terms} ({entry.terms_address})"
    source = Source.build(
        key=entry.id,
        title=entry.title,
        kind=SOURCE_KIND,
        digest=digest_bytes(data),
        locator=_locator(path) if manifest.origin == "written" else entry.source,
        terms=terms,
    )
    return CorpusDocument(
        entry=entry, path=path, data=data, source=source, text_path=text_path, text=text
    )


def read_corpus(corpus: str, *, root: Path | None = None) -> CorpusRead:
    """Read every document of a corpus and check every file against the manifest.

    Every file in the corpus folder must be a committed document or its twin, a copy in
    ``fetched/`` of a fetch-only document, or the manifest, ``README.md`` or ``.gitignore``. A
    folder the setting names may hold other files, since it is not the corpus's own. Every listed
    document must be present with the digest recorded. The first fault stops the read, naming the
    document and the file.

    Args:
        corpus: The corpus's name, for example ``harbour-mutual-bank``.
        root: One folder to look in; by default every folder of ``corpus_roots``.

    Returns:
        The manifest, the corpus folder, the documents in manifest order and the line that states
        the count.

    Raises:
        CorpusNotFoundError: If there is no such corpus, or there are two.
        CorpusManifestError: If the manifest is missing or does not validate.
        CorpusFileError: If a listed file is missing, a file is accounted for by no entry, or the
            setting names no folder.
        DocumentNotFetchedError: If a fetch-only document is not in the folder it is read from.
        CorpusDigestError: If a document's bytes or its twin's do not have the recorded digest.
    """
    folder = corpus_folder(corpus, root=root)
    manifest = load_manifest(folder)
    _check_no_stray(corpus, folder, manifest)
    documents = tuple(_read_document(corpus, folder, manifest, e) for e in manifest.documents)
    total = len(manifest.documents)
    line = f"{corpus}: {len(documents)} of {total} documents read, every digest checked"
    return CorpusRead(manifest=manifest, folder=folder, documents=documents, line=line)
