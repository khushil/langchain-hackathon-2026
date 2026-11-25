"""Fetch the published documents a corpus lists as fetch only, each checked against its digest.

Run as ``python -m context.corpus_fetch <corpus>`` from the topic's folder. A document is written
into the folder its corpus reads fetch-only documents from (the folder the manifest's setting names,
or the corpus's ``fetched/`` folder) only when its bytes have the digest the manifest records, so
the corpus reads the same bytes on every machine or not at all. Text twins are not fetched: a
publisher serves the document, and its twin is made from it where it is read.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from context.corpus import (
    CorpusDigestError,
    CorpusError,
    corpus_folder,
    document_path,
    documents_folder,
    load_manifest,
)
from fsi_common.ids import digest_bytes

TIMEOUT_SECONDS = 60
USER_AGENT = "fsi-compliance-brief corpus fetch"


class CorpusFetchError(CorpusError):
    """A document's address could not be fetched."""


@dataclass(frozen=True)
class FetchResult:
    """What a fetch did, by document id, and the line that states the counts."""

    fetched: list[str]
    present: list[str]
    committed: list[str]
    line: str


def open_url(address: str) -> bytes:
    """Return the bytes an https address serves.

    Args:
        address: The document's address.

    Returns:
        The response body.

    Raises:
        CorpusFetchError: If the request fails or the server answers with an error.
    """
    request = urllib.request.Request(address, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise CorpusFetchError(f"{address} could not be fetched: {exc}.") from exc


def fetch_corpus(
    corpus: str, *, root: Path | None = None, opener: Callable[[str], bytes] = open_url
) -> FetchResult:
    """Fetch every fetch-only document of a corpus.

    A committed document is never fetched. A fetched copy already present with the right digest is
    left as it is; one with another digest is fetched again. Bytes whose digest differs from the
    manifest's are refused and nothing is written for that document.

    Args:
        corpus: The corpus's name.
        root: One folder of corpora to look in; by default every folder of ``corpus_roots``.
        opener: The function that returns an address's bytes; a test passes a fake.

    Returns:
        The ids fetched, already present and committed, with the line that states the counts.

    Raises:
        CorpusNotFoundError: If there is no such corpus.
        CorpusManifestError: If its manifest is missing or does not validate.
        CorpusFileError: If the manifest's setting names no folder.
        CorpusFetchError: If an address cannot be fetched.
        CorpusDigestError: If fetched bytes do not have the recorded digest.
    """
    folder = corpus_folder(corpus, root=root)
    manifest = load_manifest(folder)
    fetched: list[str] = []
    present: list[str] = []
    committed: list[str] = []
    for entry in manifest.documents:
        if entry.holding == "committed":
            committed.append(entry.id)
            continue
        path = document_path(folder, manifest, entry)
        if path.is_file() and digest_bytes(path.read_bytes()) == entry.digest:
            present.append(entry.id)
            continue
        data = opener(entry.source)
        if digest_bytes(data) != entry.digest:
            raise CorpusDigestError(
                f"{entry.id} of {corpus}, fetched from {entry.source}, has the digest "
                f"{digest_bytes(data)}, and its manifest records {entry.digest}; nothing was "
                "written. The publisher may have changed the document since it was recorded."
            )
        documents_folder(folder, manifest).mkdir(exist_ok=True)
        path.write_bytes(data)
        fetched.append(entry.id)
    wanted = len(fetched) + len(present)
    line = (
        f"{corpus}: {len(fetched)} of {wanted} fetch-only documents were fetched, "
        f"{len(present)} already present, {len(committed)} committed"
    )
    return FetchResult(fetched=fetched, present=present, committed=committed, line=line)


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    opener: Callable[[str], bytes] = open_url,
) -> int:
    """Fetch the corpus named on the command line and print what was done.

    Args:
        argv: The arguments after the program name: one corpus name.
        root: One folder of corpora to look in; by default every folder of ``corpus_roots``.
        opener: The function that returns an address's bytes.

    Returns:
        0 when every fetch-only document is present with its digest, 1 otherwise.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("Name one corpus: python -m context.corpus_fetch <corpus>", file=sys.stderr)
        return 1
    try:
        result = fetch_corpus(args[0], root=root, opener=opener)
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(result.line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
