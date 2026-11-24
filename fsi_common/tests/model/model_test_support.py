"""Fakes shared by the model adapter's tests: a scripted headless runner and its output."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fsi_common.model.headless import RawRun

ISOLATED_INIT: dict[str, Any] = {
    "type": "system",
    "subtype": "init",
    "cwd": "/tmp/fsi-model-test",
    "model": "claude-sonnet-5-5",
    "tools": [],
    "mcp_servers": [],
    "plugins": [],
    "slash_commands": [],
    "skills": [],
    "agents": [],
    "apiKeySource": "none",
    "claude_code_version": "2.1.302",
}

USAGE = {
    "input_tokens": 10,
    "cache_creation_input_tokens": 100,
    "cache_read_input_tokens": 50,
    "output_tokens": 7,
}


def make_stream(
    *,
    result: str = "",
    structured: Any = None,
    usage: dict[str, Any] | None = None,
    is_error: bool = False,
    subtype: str = "success",
    init: dict[str, Any] | None = None,
    extra_result: dict[str, Any] | None = None,
) -> str:
    """Build the stdout of one `claude -p --output-format stream-json --verbose` run."""
    start = dict(init or ISOLATED_INIT)
    if init is None and structured is not None:
        start["tools"] = ["StructuredOutput"]
    events: list[dict[str, Any]] = [start]
    events.append({"type": "assistant", "message": {"content": [{"type": "text", "text": result}]}})
    final: dict[str, Any] = {
        "type": "result",
        "subtype": subtype,
        "is_error": is_error,
        "result": result,
        "num_turns": 1,
        "duration_ms": 1234,
        "stop_reason": "end_turn",
        "usage": dict(usage if usage is not None else USAGE),
        "total_cost_usd": 0.01,
    }
    if structured is not None:
        final["structured_output"] = structured
    final.update(extra_result or {})
    events.append(final)
    return "\n".join(json.dumps(event) for event in events) + "\n"


@dataclass
class FakeCall:
    """One call the fake runner received."""

    argv: list[str]
    stdin: str
    env: dict[str, str]
    cwd: str
    timeout: float


Responder = Callable[[FakeCall], RawRun]


@dataclass
class FakeRunner:
    """Stands in for the headless subprocess; answers each call with `responder`."""

    responder: Responder
    delay_s: float = 0.0
    calls: list[FakeCall] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def run(
        self, argv: list[str], *, stdin: str, env: dict[str, str], cwd: str, timeout: float
    ) -> RawRun:
        """Record the call and answer it synchronously."""
        call = FakeCall(list(argv), stdin, dict(env), cwd, timeout)
        with self._lock:
            self.calls.append(call)
        if self.delay_s:
            time.sleep(self.delay_s)
        return self.responder(call)

    async def arun(
        self, argv: list[str], *, stdin: str, env: dict[str, str], cwd: str, timeout: float
    ) -> RawRun:
        """Record the call and answer it on the event loop."""
        call = FakeCall(list(argv), stdin, dict(env), cwd, timeout)
        with self._lock:
            self.calls.append(call)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        return self.responder(call)


def flag_value(argv: list[str], flag: str) -> str | None:
    """Return the value that follows `flag` in `argv`, or None when the flag is absent."""
    if flag not in argv:
        return None
    return argv[argv.index(flag) + 1]


def schema_of(call: FakeCall) -> dict[str, Any] | None:
    """Return the envelope schema a call carried, or None when it carried none."""
    raw = flag_value(call.argv, "--json-schema")
    return json.loads(raw) if raw is not None else None


def text_reply(text: str) -> Responder:
    """A responder that answers every call with plain text."""
    return lambda call: RawRun(0, make_stream(result=text), "")


def envelope_reply(content: str, tool_calls: list[dict[str, Any]]) -> Responder:
    """A responder that answers every call with one envelope."""
    payload = {"content": content, "tool_calls": tool_calls}
    return lambda call: RawRun(0, make_stream(structured=payload), "")
