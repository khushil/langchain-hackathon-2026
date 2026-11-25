"""Fetch a regulation from its publisher, check the digest the manifest records, and cache it."""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path

from context.regulations.errors import DigestMismatchError, RegulationFetchError
from context.regulations.manifest import CACHE_DIR, REGULATIONS_DIR, RegulationEntry
from context.regulations.supervisory_statement import find_pdftotext
from fsi_common.ids import digest_bytes

Opener = Callable[[str, Mapping[str, str]], bytes]
"""Something that returns the bytes at an address, given the headers to send."""

USER_AGENT = "compliance-brief-reader/1.0 (fetches published regulation text for a build)"
TIMEOUT_SECONDS = 30
"""The longest a single step of a fetch (connecting, or waiting for the next bytes) may take."""

OVERALL_CAP_SECONDS = 90
"""The longest a whole fetch may take, however the bytes arrive."""

_CHUNK = 65536


def urllib_opener(address: str, headers: Mapping[str, str]) -> bytes:
    """Fetch an address with the standard library, following redirects.

    Args:
        address: The https address.
        headers: Headers to send beside the reader's own user agent.

    Returns:
        The response body.
    """
    request = urllib.request.Request(address, headers={"User-Agent": USER_AGENT, **headers})
    started = time.monotonic()
    body = bytearray()
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - https checked
        status = response.status
        while chunk := response.read(_CHUNK):
            body.extend(chunk)
            if time.monotonic() - started > OVERALL_CAP_SECONDS:
                raise RegulationFetchError(
                    f"{address} was still sending after {OVERALL_CAP_SECONDS} seconds, so the "
                    "fetch was given up."
                )
    if status != 200:
        raise RegulationFetchError(
            f"{address} answered HTTP {status} with {len(body)} bytes; the page is unreadable "
            "to this reader, which does not pass a challenge page."
        )
    return bytes(body)


def fetch_bytes(
    address: str, headers: Mapping[str, str], *, opener: Opener = urllib_opener
) -> bytes:
    """Fetch the bytes at an https address.

    Args:
        address: The address; it must begin with https.
        headers: Headers to send.
        opener: What fetches; tests give a fake.

    Returns:
        The bytes.

    Raises:
        RegulationFetchError: If the address is not https or the request fails.
    """
    if not address.startswith("https://"):
        raise RegulationFetchError(f"The address {address} is not https, so it is not fetched.")
    try:
        body = opener(address, headers)
    except (OSError, urllib.error.URLError) as exc:
        raise RegulationFetchError(f"Fetching {address} failed: {exc}.") from exc
    if not body:
        raise RegulationFetchError(
            f"{address} returned an empty body, so there is no text to read."
        )
    return body


def check_digest(entry: RegulationEntry, data: bytes, *, where: str) -> None:
    """Check that bytes are the bytes the manifest records.

    Args:
        entry: The manifest entry.
        data: The bytes.
        where: ``fetched`` or ``cached``, for the message.

    Raises:
        DigestMismatchError: If the digest differs; both digests are named.
    """
    got = digest_bytes(data)
    if got != entry.digest:
        raise DigestMismatchError(
            f"The {where} bytes of {entry.key} do not match the manifest: expected {entry.digest}, "
            f"got {got}. The publisher may have changed the text; nothing was used or kept."
        )


def require_tools(entry: RegulationEntry) -> None:
    """Check that the program a regulation's reader needs is installed, before any fetch.

    Args:
        entry: The manifest entry.

    Raises:
        RegulationToolMissingError: If the entry is read from a PDF and ``pdftotext`` is missing.
    """
    if entry.reader == "supervisory_statement":
        find_pdftotext()


def resolve_cache_dir(explicit: Path | None = None) -> Path:
    """Return the folder fetched texts are cached in.

    Args:
        explicit: A folder the caller names, which wins.

    Returns:
        The explicit folder, else the folder ``REGULATIONS_CACHE_DIR`` names, else the default
        folder beside the manifest. A copy named from outside the tree is used only when its
        digest matches the manifest's.
    """
    if explicit is not None:
        return explicit
    named = os.environ.get("REGULATIONS_CACHE_DIR")
    return Path(named) if named else CACHE_DIR


def ensure_regulation(
    entry: RegulationEntry,
    *,
    cache_dir: Path | None = None,
    opener: Opener = urllib_opener,
    root: Path = REGULATIONS_DIR,
) -> bytes:
    """Return a regulation's bytes, fetching only when nothing held or cached matches.

    A text held in the repository is read from there. Otherwise a cached copy is used when its
    digest matches the manifest's; a cached copy that is absent, or whose digest differs, is
    replaced by a fetch from the publisher, whose bytes must match in their turn.

    Args:
        entry: The manifest entry.
        cache_dir: The cache folder; by default the one ``resolve_cache_dir`` gives.
        opener: What fetches; tests give a fake.
        root: The folder a held text's path is relative to.

    Returns:
        The bytes, whose digest equals the manifest's.

    Raises:
        DigestMismatchError: If a held text, or the bytes fetched, differ from the manifest's
            digest.
        RegulationFetchError: If the fetch fails.
        RegulationToolMissingError: If the reader needs a program that is not installed.
    """
    require_tools(entry)
    if entry.text_file:
        data = (root / entry.text_file).read_bytes()
        check_digest(entry, data, where="held")
        return data
    folder = resolve_cache_dir(cache_dir)
    target = folder / entry.cache_file
    if target.exists():
        cached = target.read_bytes()
        if digest_bytes(cached) == entry.digest:
            return cached
    data = fetch_bytes(entry.address, entry.request_headers, opener=opener)
    check_digest(entry, data, where="fetched")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".gitignore").write_text("*\n", encoding="utf-8")
    target.write_bytes(data)
    return data


def verify_live(entry: RegulationEntry, *, opener: Opener = urllib_opener) -> int:
    """Fetch a regulation from its publisher now and compare it with the manifest's digest.

    Args:
        entry: The manifest entry.
        opener: What fetches; tests give a fake.

    Returns:
        The size of the bytes fetched.

    Raises:
        DigestMismatchError: If the publisher's bytes differ from the manifest's digest.
        RegulationFetchError: If the fetch fails.
    """
    data = fetch_bytes(entry.address, entry.request_headers, opener=opener)
    check_digest(entry, data, where="fetched")
    return len(data)
