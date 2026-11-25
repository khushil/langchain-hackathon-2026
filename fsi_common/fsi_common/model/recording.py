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

from fsi_common.model.errors import RecordingShapeError, ReplayMissError

FORMAT_VERSION = 2
"""Bumped whenever the prompt the adapter renders changes, so old recordings stop matching."""

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

INIT_FIELDS = (
    "model",
    "tools",
    "mcp_servers",
    "plugins",
    "slash_commands",
    "skills",
    "agents",
    "apiKeySource",
    "claude_code_version",
)
"""The fields of the run's start event kept as evidence that the call ran isolated."""

TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
"""The token counts kept from a reply's usage."""

RECORDING_SHAPE: dict[str, Any] = {
    "request_sha256": "str",
    "request": {
        "format": "int",
        "model": "str",
        "effort": "str|null",
        "system": "str",
        "messages": "any",
        "schema": "any",
    },
    "response": {
        "content": "str",
        "tool_calls": [{"name": "str", "args": "any"}],
        "model_reported": "str|null",
        "usage": dict.fromkeys(TOKEN_FIELDS, "int"),
    },
    "meta": {
        "recorded_at": "str",
        "duration_s": "number",
        "init": {
            "model": "str|null",
            "tools": ["str"],
            "mcp_servers": ["str"],
            "plugins": ["str"],
            "slash_commands": ["str"],
            "skills": ["str"],
            "agents": ["str"],
            "apiKeySource": "str|null",
            "claude_code_version": "str|null",
        },
    },
}
"""Every field a recording may hold, and its shape; JSON-ready, so a check outside the product
can keep a copy and compare it.

A dict admits only its own keys, each optional; a one-item list is a list whose every item has
that shape; a string names a value's type: "str", "int", "number", "str|null", or "any" for the
free content of the model's messages, schemas and tool-call arguments. A recording never keeps
the account's rate-limit state, its usage windows, plan or overage settings, or a call's cost:
those describe the signed-in account, not the call.
"""

_TYPES: dict[str, Any] = {
    "str": lambda v: isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "str|null": lambda v: v is None or isinstance(v, str),
    "any": lambda v: True,
}


def recording_problems(data: Any, *, shape: Any = RECORDING_SHAPE, path: str = "") -> list[str]:
    """Return every place `data` departs from the recording's shape, sorted.

    Args:
        data: A recording as read from disk, or a part of one.
        shape: The part of `RECORDING_SHAPE` that applies to `data`.
        path: Where `data` sits in the recording, for example `response.tool_calls[0]`.

    Returns:
        The path of each field outside the allow-list (`meta.rate_limit`), and of each value in
        another shape, followed by what was expected (`response.usage (expected an object)`);
        empty when the recording is clean.
    """
    where = path or "the recording"
    if isinstance(shape, str):
        return [] if _TYPES[shape](data) else [f"{where} (expected {shape})"]
    if isinstance(shape, list):
        if not isinstance(data, list):
            return [f"{where} (expected a list)"]
        found: list[str] = []
        for index, item in enumerate(data):
            found.extend(recording_problems(item, shape=shape[0], path=f"{path}[{index}]"))
        return sorted(found)
    if not isinstance(data, dict):
        return [f"{where} (expected an object)"]
    found = []
    for key, value in data.items():
        inner = f"{path}.{key}" if path else str(key)
        if key not in shape:
            found.append(inner)
        else:
            found.extend(recording_problems(value, shape=shape[key], path=inner))
    return sorted(found)


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

    request_sha256: str
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
        """Write a recording atomically and return its path.

        Raises:
            RecordingShapeError: If the recording holds a field outside the allow-list, or a value
                in another shape.
        """
        path = self._path(recording.request_sha256)
        extra = recording_problems(asdict(recording))
        if extra:
            raise RecordingShapeError(recording.request_sha256, extra)
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

    def has(self, key: str) -> bool:
        """Say whether a recording exists for a request hash."""
        return self._path(key).is_file()

    def load(self, key: str) -> Recording:
        """Read the recording for a request hash.

        Raises:
            ReplayMissError: If no recording exists, or the file holds another request.
            RecordingShapeError: If the file holds a field outside the allow-list, or a value in
                another shape.
            ValueError: If the key is not a SHA-256 hex digest.
        """
        path = self._path(key)
        if not path.is_file():
            raise ReplayMissError(key)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("request_sha256") != key or request_hash(data.get("request", {})) != key:
            raise ReplayMissError(key, reason="a file that holds a different request")
        extra = recording_problems(data)
        if extra:
            raise RecordingShapeError(path.name, extra)
        return Recording(**data)
