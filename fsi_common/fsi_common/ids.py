"""Content-derived identifiers and SHA-256 digests over canonical JSON."""

from __future__ import annotations

import hashlib
import json
from typing import Any

ID_HEX_LENGTH = 16
DIGEST_PREFIX = "sha256:"


def canonical_json(value: Any) -> str:
    """Serialise a JSON value in the one form every digest and id is computed over.

    Keys are sorted, separators carry no spaces, non-ASCII text is kept as UTF-8 and
    non-finite numbers are refused, so the same value always gives the same bytes.

    Args:
        value: A JSON-compatible value (dicts, lists, strings, integers, booleans, None).

    Returns:
        The canonical JSON text.

    Raises:
        ValueError: If the value holds a NaN or an infinity.
        TypeError: If the value holds something JSON cannot represent.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest_bytes(data: bytes) -> str:
    """Return the digest of some bytes as ``sha256:`` and 64 hex characters.

    Args:
        data: The bytes to digest, for example a source file read in binary mode.

    Returns:
        The digest string.
    """
    return DIGEST_PREFIX + hashlib.sha256(data).hexdigest()


def digest_text(text: str) -> str:
    """Return the digest of a text's UTF-8 bytes, with no normalisation applied.

    Args:
        text: The text, as the caller has fixed it (for example one paragraph).

    Returns:
        The digest string.
    """
    return digest_bytes(text.encode("utf-8"))


def digest_json(value: Any) -> str:
    """Return the digest of a JSON value's canonical form.

    Args:
        value: A JSON-compatible value.

    Returns:
        The digest string.
    """
    return digest_text(canonical_json(value))


def content_id(prefix: str, basis: Any) -> str:
    """Return ``<prefix>:`` and the first 16 hex characters of the digest of ``basis``.

    Args:
        prefix: The record family, for example ``fact``.
        basis: The JSON value the id is derived from; never a clock, a counter or a position.

    Returns:
        The content-derived id.
    """
    return f"{prefix}:{digest_json(basis)[len(DIGEST_PREFIX) : len(DIGEST_PREFIX) + ID_HEX_LENGTH]}"
