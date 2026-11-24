"""Request hashing, tool-call id minting and the on-disk store of recorded headless calls."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fsi_common.model.errors import ReplayMissError

FORMAT_VERSION = 2
"""Bumped whenever the prompt the adapter renders changes, so old recordings stop matching."""

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(value: Any) -> str:
    """Serialise a value the same way every time: sorted keys, no spaces, UTF-8 kept."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_request(
    *,
    model: str,
    effort: str | None,
    system: str,
    messages: list[dict[str, Any]],
    schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the canonical form of one call: everything that decides what the model sees.

    Args:
        model: The model name passed to `--model`.
        effort: The effort passed to `--effort`, or None.
        system: The caller's system text.
        messages: The canonical turns from `transcript.canonical_messages`.
        schema: The envelope schema, or None for a call with no bound tools.

    Returns:
        A JSON-ready dict that also carries the adapter's format version.
    """
    return {
        "format": FORMAT_VERSION,
        "model": model,
        "effort": effort,
        "system": system,
        "messages": messages,
        "schema": schema,
    }


def request_hash(request: dict[str, Any]) -> str:
    """Return the SHA-256 hex digest of a canonical request."""
    return hashlib.sha256(_canonical_json(request).encode("utf-8")).hexdigest()


def mint_tool_call_id(key: str, position: int, name: str, args: dict[str, Any]) -> str:
    """Mint a tool-call id from the call's content, so a replay yields the same id.

    Args:
        key: The request hash of the call that produced the tool call.
        position: The tool call's position in that reply.
        name: The tool's name.
        args: The tool call's arguments.

    Returns:
        `call_` followed by 24 hex digits.
    """
    seed = f"{key}:{position}:{name}:{_canonical_json(args)}"
    return "call_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class Recording:
    """One recorded call: its canonical request, the reply it produced, and how it ran."""

    key: str
    request: dict[str, Any]
    response: dict[str, Any]
    meta: dict[str, Any]


class RecordingStore:
    """A directory of recordings, one JSON file per request hash."""

    def __init__(self, root: Path) -> None:
        """Use `root` as the store; it is created on the first save."""
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if not _HEX64.match(key):
            raise ValueError(f"The key {key!r} is not a SHA-256 hex digest.")
        return self.root / f"{key}.json"

    def save(self, recording: Recording) -> Path:
        """Write a recording atomically and return its path."""
        path = self._path(recording.key)
        self.root.mkdir(parents=True, exist_ok=True)
        text = json.dumps(asdict(recording), indent=1, sort_keys=True, ensure_ascii=False)
        handle, temp = tempfile.mkstemp(dir=self.root, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text + "\n")
            os.replace(temp, path)
        except OSError:
            Path(temp).unlink(missing_ok=True)
            raise
        return path

    def load(self, key: str) -> Recording:
        """Read the recording for a request hash.

        Raises:
            ReplayMissError: If no recording exists, or the file holds another request.
            ValueError: If the key is not a SHA-256 hex digest.
        """
        path = self._path(key)
        if not path.is_file():
            raise ReplayMissError(key)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("key") != key or request_hash(data.get("request", {})) != key:
            raise ReplayMissError(key, reason="a file that holds a different request")
        return Recording(**data)
