"""The isolated `claude -p` command line, its environment, its runner and its output parser."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fsi_common.model.errors import (
    HeadlessCallError,
    HeadlessTimeoutError,
    IsolationError,
    MalformedResponseError,
    ModelConfigError,
)

EFFORTS = ("low", "medium", "high", "xhigh", "max")

MAX_ARGUMENT_CHARS = 120_000
"""Linux caps one argument at 128 KiB, so the system prompt and schema stay below this."""

ISOLATION_FLAGS = (
    "--safe-mode",
    "--tools",
    "--strict-mcp-config",
    "--setting-sources",
    "--settings",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--permission-prompts",
)

BUILTIN_PLUGINS_OFF = (
    "cc-plugin-agents-md@builtin",
    "cc-plugin-telemetry@builtin",
    "cc-plugin-plugin-authoring@builtin",
)
"""Claude Code 2.1.302 loads these three built-in plugins even in safe mode; each is set off."""

_PLUGINS_OFF_SETTINGS = json.dumps(
    {"enabledPlugins": dict.fromkeys(BUILTIN_PLUGINS_OFF, False)}, separators=(",", ":")
)

_ISOLATION_ARGS = [
    "--safe-mode",
    "--tools",
    "",
    "--strict-mcp-config",
    "--setting-sources",
    "",
    "--settings",
    _PLUGINS_OFF_SETTINGS,
    "--disable-slash-commands",
    "--no-session-persistence",
    "--permission-prompts",
    "none",
]

FIXED_ENV = {
    "LANG": "C.UTF-8",
    "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1",
}
"""Variables every call gets whatever the parent holds; the built-in agents are switched off."""

PASSED_ENV = ("HOME",)
"""The only variables copied from the parent: Claude Code finds the account's login under HOME."""

ALLOWED_PLUGINS: frozenset[str] = frozenset()
"""Plugins a call may start with; any other plugin in the start event fails the call."""

_EMPTY_FIELDS = ("mcp_servers", "slash_commands", "skills", "agents")

SCHEMA_TOOL = "StructuredOutput"
"""The one tool Claude Code adds itself when `--json-schema` is passed: the model answers through
it and Claude Code validates the answer against the schema. No other tool may load."""


@dataclass(frozen=True)
class RawRun:
    """What one process run produced."""

    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class HeadlessResult:
    """The start event and the result event of one headless call."""

    init: dict[str, Any]
    result: dict[str, Any]
    rate_limit: dict[str, Any] | None


def build_argv(
    *,
    claude_path: str,
    model: str,
    effort: str | None,
    system_prompt: str,
    schema: dict[str, Any] | None,
) -> list[str]:
    """Build the isolated command line; the prompt itself goes on standard input.

    Raises:
        ModelConfigError: If the model, effort or argument sizes cannot be passed safely.
    """
    if not model or model.startswith("-"):
        raise ModelConfigError(f"The model must be a non-empty name, not {model!r}.")
    if effort is not None and effort not in EFFORTS:
        raise ModelConfigError(f"The effort must be one of {', '.join(EFFORTS)}, not {effort!r}.")
    if len(system_prompt) > MAX_ARGUMENT_CHARS:
        raise ModelConfigError(
            f"The system prompt is {len(system_prompt)} characters; one argument may carry at "
            f"most {MAX_ARGUMENT_CHARS}."
        )
    argv = [claude_path, "-p", "--output-format", "stream-json", "--verbose", "--model", model]
    if effort is not None:
        argv += ["--effort", effort]
    argv += ["--system-prompt", system_prompt, *_ISOLATION_ARGS]
    if schema is not None:
        text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        if len(text) > MAX_ARGUMENT_CHARS:
            raise ModelConfigError(f"The envelope schema is {len(text)} characters; too long.")
        argv += ["--json-schema", text]
    return argv


def resolve_claude(claude_path: str) -> str:
    """Return the absolute path of the Claude Code executable, looked up on this process's PATH.

    Raises:
        HeadlessCallError: If no such executable is found.
    """
    found = shutil.which(claude_path)
    if found is None:
        raise HeadlessCallError(
            f"Claude Code was not found as {claude_path!r} on PATH; install it and sign in, "
            "or run in replay mode.",
            exit_code=None,
        )
    return os.path.abspath(found)


def build_env(claude_path: str) -> dict[str, str]:
    """Build the call's environment from an allow-list; nothing else of the parent's passes."""
    env = {name: os.environ[name] for name in PASSED_ENV if name in os.environ}
    bin_dir = str(Path(claude_path).parent) if os.sep in claude_path else ""
    env["PATH"] = ":".join(part for part in (bin_dir, "/usr/bin", "/bin") if part)
    env.update(FIXED_ENV)
    return env


def parse_stream(stdout: str, *, exit_code: int, stderr: str) -> HeadlessResult:
    """Read the start and result events out of a `stream-json` run.

    Raises:
        HeadlessCallError: If the process failed or its result is flagged as an error.
        MalformedResponseError: If the output is not the expected event stream.
    """
    if exit_code != 0:
        raise HeadlessCallError(
            f"The headless call exited with code {exit_code}.", exit_code=exit_code, stderr=stderr
        )
    init: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    rate_limit: dict[str, Any] | None = None
    for number, line in enumerate(stdout.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise MalformedResponseError(f"Line {number} of the output is not JSON.") from error
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            init = event
        elif kind == "result":
            result = event
        elif kind == "rate_limit_event":
            rate_limit = event.get("rate_limit_info")
    if result is None:
        raise MalformedResponseError("The output has no result event.")
    if init is None:
        raise MalformedResponseError("The output has no init event, so isolation is unproven.")
    if result.get("is_error") or result.get("subtype") != "success":
        raise HeadlessCallError(
            f"The headless call ended with {result.get('subtype')!r}: {result.get('result')!r}.",
            exit_code=exit_code,
            stderr=stderr,
        )
    return HeadlessResult(init=init, result=result, rate_limit=rate_limit)


def _model_matches(reported: str, expected: str) -> bool:
    if expected in {"opus", "sonnet", "haiku", "fable"}:
        return reported.startswith(f"claude-{expected}")
    return reported == expected


def check_isolation(init: dict[str, Any], *, expected_model: str, has_schema: bool = False) -> None:
    """Refuse a call whose start event shows anything loaded beyond the bare model.

    Args:
        init: The run's start event.
        expected_model: The model the call asked for.
        has_schema: Whether the call passed `--json-schema`; only then may `StructuredOutput` load.

    Raises:
        IsolationError: If a tool, MCP server, plugin, command, skill or agent was loaded, a key
            other than the account login was used, or another model family answered.
    """
    problems = [f"{field}={init.get(field)!r}" for field in _EMPTY_FIELDS if init.get(field)]
    allowed_tools = [SCHEMA_TOOL] if has_schema else []
    tools = list(init.get("tools") or [])
    if tools and tools != allowed_tools:
        problems.append(f"tools={tools!r}")
    plugins = {plugin.get("source", plugin.get("name")) for plugin in init.get("plugins") or []}
    if plugins - ALLOWED_PLUGINS:
        problems.append(f"plugins={sorted(plugins - ALLOWED_PLUGINS)!r}")
    if init.get("apiKeySource", "none") != "none":
        problems.append(f"apiKeySource={init.get('apiKeySource')!r}")
    if not _model_matches(str(init.get("model", "")), expected_model):
        problems.append(f"model={init.get('model')!r} (asked for {expected_model!r})")
    if problems:
        raise IsolationError("The headless call was not isolated: " + "; ".join(problems) + ".")


class SubprocessRunner:
    """Runs the headless command as a child process, without a shell."""

    def run(
        self, argv: list[str], *, stdin: str, env: dict[str, str], cwd: str, timeout: float
    ) -> RawRun:
        """Run the command to completion from a thread.

        Raises:
            HeadlessTimeoutError: If it runs past `timeout` seconds; the child is killed.
        """
        try:
            done = subprocess.run(
                argv,
                input=stdin.encode("utf-8"),
                capture_output=True,
                env=env,
                cwd=cwd,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise HeadlessTimeoutError(
                f"The headless call did not finish within {timeout} s and was stopped.",
                exit_code=None,
                stderr=(error.stderr or b"").decode("utf-8", "replace"),
            ) from error
        return RawRun(
            done.returncode,
            done.stdout.decode("utf-8", "replace"),
            done.stderr.decode("utf-8", "replace"),
        )

    async def arun(
        self, argv: list[str], *, stdin: str, env: dict[str, str], cwd: str, timeout: float
    ) -> RawRun:
        """Run the command to completion on the event loop.

        Raises:
            HeadlessTimeoutError: If it runs past `timeout` seconds; the child is killed.
        """
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=cwd,
        )
        try:
            async with asyncio.timeout(timeout):
                out, err = await process.communicate(stdin.encode("utf-8"))
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise HeadlessTimeoutError(
                f"The headless call did not finish within {timeout} s and was stopped.",
                exit_code=None,
            ) from error
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        return RawRun(
            process.returncode if process.returncode is not None else -1,
            out.decode("utf-8", "replace"),
            err.decode("utf-8", "replace"),
        )
