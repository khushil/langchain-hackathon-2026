"""A LangChain chat model whose every call is one isolated, capped, recordable `claude -p` run."""

from __future__ import annotations

import asyncio
import atexit
import shutil
import tempfile
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from pydantic import ConfigDict, Field, PrivateAttr

from fsi_common.model.envelope import (
    ToolSpec,
    build_envelope_schema,
    normalise_tools,
    parse_envelope,
)
from fsi_common.model.errors import ModelConfigError
from fsi_common.model.gate import PROCESS_CAP, ConcurrencyGate, process_gate
from fsi_common.model.headless import (
    EFFORTS,
    HeadlessResult,
    SubprocessRunner,
    build_argv,
    build_env,
    check_isolation,
    parse_stream,
    resolve_claude,
)
from fsi_common.model.recording import (
    INIT_FIELDS,
    TOKEN_FIELDS,
    Recording,
    RecordingStore,
    canonical_request,
    mint_tool_call_id,
    request_hash,
)
from fsi_common.model.transcript import canonical_messages, render_prompt, render_system

Mode = Literal["live", "record", "replay"]
MODES = ("live", "record", "replay")
DEFAULT_TIMEOUT_S = 600.0


@dataclass(frozen=True)
class CallRecord:
    """Timing of one model call, kept in memory for the measured runs."""

    request_hash: str
    mode: str
    started_at: str
    duration_s: float
    in_flight_at_start: int


_RECORDS: list[CallRecord] = []
_RECORDS_LOCK = threading.Lock()
_RECORD_LOCKS: dict[str, threading.Lock] = {}
_ARECORD_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}


def _record_lock(key: str) -> threading.Lock:
    """One lock per request hash, so two identical requests in record mode make one call."""
    with _RECORDS_LOCK:
        return _RECORD_LOCKS.setdefault(key, threading.Lock())


def _arecord_lock(key: str) -> asyncio.Lock:
    """The same for coroutines, one lock per running loop and request hash."""
    with _RECORDS_LOCK:
        return _ARECORD_LOCKS.setdefault((id(asyncio.get_running_loop()), key), asyncio.Lock())


_WORKDIR: list[str] = []


def call_records() -> list[CallRecord]:
    """Return a copy of every call this process has made since the last reset."""
    with _RECORDS_LOCK:
        return list(_RECORDS)


def reset_call_records() -> None:
    """Forget the calls recorded so far."""
    with _RECORDS_LOCK:
        _RECORDS.clear()


def _empty_workdir() -> str:
    """An empty directory, made once per process, for the calls' working directory."""
    with _RECORDS_LOCK:
        if not _WORKDIR:
            path = tempfile.mkdtemp(prefix="fsi-model-")
            atexit.register(shutil.rmtree, path, True)
            _WORKDIR.append(path)
        return _WORKDIR[0]


def _token_counts(raw: dict[str, Any] | None) -> dict[str, int]:
    """Keep only the token counts of a reply's usage; the rest describes the account."""
    return {k: int(raw[k]) for k in TOKEN_FIELDS if raw and raw.get(k) is not None}


def _usage(raw: dict[str, Any] | None) -> UsageMetadata | None:
    if not raw:
        return None
    cache_read = int(raw.get("cache_read_input_tokens") or 0)
    cache_creation = int(raw.get("cache_creation_input_tokens") or 0)
    inputs = int(raw.get("input_tokens") or 0) + cache_read + cache_creation
    outputs = int(raw.get("output_tokens") or 0)
    usage: UsageMetadata = {
        "input_tokens": inputs,
        "output_tokens": outputs,
        "total_tokens": inputs + outputs,
    }
    if cache_read or cache_creation:
        usage["input_token_details"] = {"cache_read": cache_read, "cache_creation": cache_creation}
    return usage


class ChatClaudeHeadless(BaseChatModel):
    """Chat model over headless Claude Code: isolated, capped, and able to record and replay."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: str
    effort: str | None = None
    mode: Mode = "live"
    recordings_dir: Path
    max_concurrency: int = PROCESS_CAP
    timeout_s: float = DEFAULT_TIMEOUT_S
    claude_path: str = "claude"
    workdir: Path | None = None
    runner: Any = Field(default=None, exclude=True)

    _gate: ConcurrencyGate = PrivateAttr()

    def model_post_init(self, context: Any, /) -> None:
        """Give each model its own cap, beneath the process-wide one."""
        self._gate = ConcurrencyGate(self.max_concurrency)

    @property
    def _llm_type(self) -> str:
        return "claude-code-headless"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model, "effort": self.effort, "mode": self.mode}

    def _get_ls_params(self, stop: list[str] | None = None, **kwargs: Any) -> Any:
        params = super()._get_ls_params(stop=stop, **kwargs)
        params["ls_provider"] = "claude-code-headless"
        params["ls_model_name"] = self.model
        return params

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        """Bind tools; they travel in the call's `--json-schema` envelope and are never run here.

        Args:
            tools: LangChain tools, Pydantic models or tool dicts.
            tool_choice: None or "auto", "any" or "required", "none", or a tool's name.
            **kwargs: Further arguments bound to every call.

        Returns:
            A runnable whose calls carry the tools.
        """
        specs = normalise_tools(tools)
        build_envelope_schema(specs, tool_choice=tool_choice)
        formatted = [
            {
                "type": "function",
                "function": {
                    "name": s.name,
                    "description": s.description,
                    "parameters": s.parameters,
                },
            }
            for s in specs
        ]
        return self.bind(tools=formatted, tool_choice=tool_choice, **kwargs)

    def _prepare(
        self, messages: list[BaseMessage], stop: list[str] | None, kwargs: dict[str, Any]
    ) -> tuple[dict[str, Any], str, list[ToolSpec], list[str], str]:
        if stop:
            raise ModelConfigError("Headless Claude Code cannot honour stop sequences.")
        specs: list[ToolSpec] = normalise_tools(kwargs.get("tools") or [])
        schema = (
            build_envelope_schema(specs, tool_choice=kwargs.get("tool_choice")) if specs else None
        )
        system, turns = canonical_messages(messages)
        request = canonical_request(
            model=self.model, effort=self.effort, system=system, messages=turns, schema=schema
        )
        argv = build_argv(
            claude_path=self.claude_path,
            model=self.model,
            effort=self.effort,
            system_prompt=render_system(system, specs),
            schema=schema,
        )
        return request, request_hash(request), specs, argv, render_prompt(turns)

    def _finish(
        self,
        key: str,
        request: dict[str, Any],
        specs: list[ToolSpec],
        raw: Any,
        started: tuple[str, float, int],
    ) -> ChatResult:
        parsed: HeadlessResult = parse_stream(
            raw.stdout, exit_code=raw.exit_code, stderr=raw.stderr
        )
        check_isolation(parsed.init, expected_model=self.model, has_schema=bool(specs))
        result = parsed.result
        if specs:
            envelope = parse_envelope(result.get("structured_output"), specs)
            content, calls = envelope.content, envelope.tool_calls
        else:
            content, calls = str(result.get("result") or ""), []
        response = {
            "content": content,
            "tool_calls": [{"name": name, "args": args} for name, args in calls],
            "usage": _token_counts(result.get("usage")),
            "model_reported": parsed.init.get("model"),
        }
        duration = time.monotonic() - started[1]
        if self.mode == "record":
            RecordingStore(self.recordings_dir).save(
                Recording(
                    request_sha256=key,
                    request=request,
                    response=response,
                    meta={
                        "recorded_at": started[0],
                        "duration_s": round(duration, 3),
                        "init": {k: parsed.init.get(k) for k in INIT_FIELDS},
                    },
                )
            )
        self._log(key, self.mode, started, duration)
        return self._to_result(key, response, self.mode)

    def _to_result(self, key: str, response: dict[str, Any], mode: str) -> ChatResult:
        tool_calls = [
            {
                "name": call["name"],
                "args": call["args"],
                "id": mint_tool_call_id(key, position, call["name"], call["args"]),
                "type": "tool_call",
            }
            for position, call in enumerate(response["tool_calls"])
        ]
        message = AIMessage(
            content=response["content"],
            tool_calls=tool_calls,
            usage_metadata=_usage(response.get("usage")),
            response_metadata={
                "mode": mode,
                "request_hash": key,
                "model_name": response.get("model_reported") or self.model,
            },
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    @staticmethod
    def _log(key: str, mode: str, started: tuple[str, float, int], duration: float) -> None:
        with _RECORDS_LOCK:
            _RECORDS.append(CallRecord(key, mode, started[0], round(duration, 3), started[2]))

    def _runner_and_argv(self, argv: list[str]) -> tuple[Any, list[str]]:
        """Pick the runner; a real run gets the absolute path of Claude Code as its argv[0]."""
        if self.runner is not None:
            return self.runner, argv
        return SubprocessRunner(), [resolve_claude(self.claude_path), *argv[1:]]

    def _replay(self, key: str) -> ChatResult:
        recording = RecordingStore(self.recordings_dir).load(key)
        self._log(key, "replay", (datetime.now(UTC).isoformat(), time.monotonic(), 0), 0.0)
        return self._to_result(key, recording.response, "replay")

    def _reuse(self, key: str) -> ChatResult:
        """In record mode, answer a request this recording already holds, as replay would.

        A recording is one draw of each request: if the same request is sent again in the same
        recording, a second live call would draw again and overwrite the first, and replay would
        then give an earlier step the later draw. So a repeated request is answered from the file.
        """
        recording = RecordingStore(self.recordings_dir).load(key)
        self._log(key, "reused", (datetime.now(UTC).isoformat(), time.monotonic(), 0), 0.0)
        return self._to_result(key, recording.response, "record")

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        request, key, specs, argv, prompt = self._prepare(messages, stop, kwargs)
        if self.mode == "replay":
            return self._replay(key)
        if self.mode == "record":
            with _record_lock(key):
                if RecordingStore(self.recordings_dir).has(key):
                    return self._reuse(key)
                return self._call(key, request, specs, argv, prompt)
        return self._call(key, request, specs, argv, prompt)

    def _call(
        self, key: str, request: dict[str, Any], specs: list[ToolSpec], argv: list[str], prompt: str
    ) -> ChatResult:
        """Make one live headless call and finish it (recording it in record mode)."""
        runner, argv = self._runner_and_argv(argv)
        with self._gate.slot(), process_gate().slot() as holders:
            started = (datetime.now(UTC).isoformat(), time.monotonic(), holders)
            raw = runner.run(
                argv,
                stdin=prompt,
                env=build_env(argv[0]),
                cwd=str(self.workdir) if self.workdir else _empty_workdir(),
                timeout=self.timeout_s,
            )
        return self._finish(key, request, specs, raw, started)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        request, key, specs, argv, prompt = self._prepare(messages, stop, kwargs)
        if self.mode == "replay":
            return self._replay(key)
        if self.mode == "record":
            async with _arecord_lock(key):
                if RecordingStore(self.recordings_dir).has(key):
                    return self._reuse(key)
                return await self._acall(key, request, specs, argv, prompt)
        return await self._acall(key, request, specs, argv, prompt)

    async def _acall(
        self, key: str, request: dict[str, Any], specs: list[ToolSpec], argv: list[str], prompt: str
    ) -> ChatResult:
        """Make one live headless call on the event loop and finish it."""
        runner, argv = self._runner_and_argv(argv)
        async with self._gate.aslot(), process_gate().aslot() as holders:
            started = (datetime.now(UTC).isoformat(), time.monotonic(), holders)
            raw = await runner.arun(
                argv,
                stdin=prompt,
                env=build_env(argv[0]),
                cwd=str(self.workdir) if self.workdir else _empty_workdir(),
                timeout=self.timeout_s,
            )
        return self._finish(key, request, specs, raw, started)


def make_chat_model(
    *,
    model: str,
    effort: str | None,
    mode: Literal["live", "record", "replay"],
    recordings_dir: Path,
    max_concurrency: int = PROCESS_CAP,
) -> ChatClaudeHeadless:
    """Build the chat model every agent in the product runs on.

    Args:
        model: A model alias such as "sonnet" or "opus", or a full model name.
        effort: "low", "medium", "high", "xhigh" or "max", or None for the model's default.
        mode: "live" calls Claude Code; "record" calls it and saves each call; "replay" answers
            only from saved calls and never starts a process.
        recordings_dir: Where recordings are saved and read.
        max_concurrency: This model's own cap, 1 to 4; the process never runs more than 4.

    Returns:
        The chat model.

    Raises:
        ModelConfigError: If an argument is outside what the adapter supports.
    """
    if mode not in MODES:
        raise ModelConfigError(f"The mode must be one of {', '.join(MODES)}, not {mode!r}.")
    if not 1 <= max_concurrency <= PROCESS_CAP:
        raise ModelConfigError(
            f"max_concurrency must be between 1 and {PROCESS_CAP}, not {max_concurrency}."
        )
    if effort is not None and effort not in EFFORTS:
        raise ModelConfigError(f"The effort must be one of {', '.join(EFFORTS)}, not {effort!r}.")
    return ChatClaudeHeadless(
        model=model,
        effort=effort,
        mode=mode,
        recordings_dir=Path(recordings_dir),
        max_concurrency=max_concurrency,
    )


__all__ = [
    "CallRecord",
    "ChatClaudeHeadless",
    "call_records",
    "make_chat_model",
    "reset_call_records",
]
