"""Tests for the headless command line, its environment, its output and its isolation check."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from typing import Any

import pytest
from model_test_support import ISOLATED_INIT, make_stream

from fsi_common.model.errors import (
    HeadlessCallError,
    HeadlessTimeoutError,
    IsolationError,
    MalformedResponseError,
    ModelConfigError,
)
from fsi_common.model.headless import (
    SubprocessRunner,
    build_argv,
    build_env,
    check_isolation,
    parse_stream,
    resolve_claude,
)


def test_argv_carries_every_isolation_flag_and_no_bypass() -> None:
    argv = build_argv(
        claude_path="/usr/bin/claude",
        model="sonnet",
        effort="low",
        system_prompt="Be brief.",
        schema=None,
    )
    assert argv[:2] == ["/usr/bin/claude", "-p"]
    for flag in (
        "--safe-mode",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
    ):
        assert flag in argv
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert json.loads(argv[argv.index("--settings") + 1]) == {
        "enabledPlugins": {
            "cc-plugin-agents-md@builtin": False,
            "cc-plugin-telemetry@builtin": False,
            "cc-plugin-plugin-authoring@builtin": False,
        }
    }
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--effort") + 1] == "low"
    assert argv[argv.index("--system-prompt") + 1] == "Be brief."
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv
    assert "--json-schema" not in argv
    assert not any("dangerously" in part for part in argv)


def test_argv_carries_the_schema_and_omits_effort_when_unset() -> None:
    schema = {"type": "object", "properties": {"content": {"type": "string"}}}
    argv = build_argv(
        claude_path="claude", model="opus", effort=None, system_prompt="S", schema=schema
    )
    assert json.loads(argv[argv.index("--json-schema") + 1]) == schema
    assert "--effort" not in argv


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"model": ""}, "model must be a non-empty name"),
        ({"model": "--help"}, "model must be a non-empty name"),
        ({"effort": "extreme"}, "effort must be one of"),
        ({"system_prompt": "x" * 120_001}, "system prompt is 120001 characters"),
    ],
)
def test_argv_refuses_bad_values(kwargs: dict[str, Any], reason: str) -> None:
    values: dict[str, Any] = {
        "claude_path": "claude",
        "model": "sonnet",
        "effort": None,
        "system_prompt": "S",
        "schema": None,
    }
    values.update(kwargs)
    with pytest.raises(ModelConfigError, match=reason):
        build_argv(**values)


def test_env_is_an_allow_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/someone")
    monkeypatch.setenv("LANGSMITH_API_KEY", "not-for-the-child")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "remapped")
    monkeypatch.setenv("CLAUDE_CODE_USE_FOUNDRY", "1")
    env = build_env("/opt/claude/bin/claude")
    assert env["HOME"] == "/home/someone"
    assert env["PATH"].split(":")[0] == "/opt/claude/bin"
    assert "LANGSMITH_API_KEY" not in env
    assert "ANTHROPIC_DEFAULT_SONNET_MODEL" not in env
    assert "CLAUDE_CODE_USE_FOUNDRY" not in env
    assert set(env) <= {"HOME", "PATH", "LANG", *env.keys()}
    assert all(not key.startswith(("ANTHROPIC_", "LANGSMITH_", "OPENAI_")) for key in env)


def test_parse_stream_returns_the_init_and_result_events() -> None:
    parsed = parse_stream(make_stream(result="OK"), exit_code=0, stderr="")
    assert parsed.init["model"] == "claude-sonnet-5-5"
    assert parsed.result["result"] == "OK"
    assert parsed.result["usage"]["output_tokens"] == 7


def test_a_non_zero_exit_raises_with_code_and_stderr_head() -> None:
    stderr = "Error: something broke\n" + "x" * 5000
    with pytest.raises(HeadlessCallError, match="exited with code 2") as caught:
        parse_stream("", exit_code=2, stderr=stderr)
    assert caught.value.exit_code == 2
    assert caught.value.stderr_head.startswith("Error: something broke")
    assert len(caught.value.stderr_head) <= 2000


def test_an_error_result_raises_even_on_exit_zero() -> None:
    stream = make_stream(is_error=True, subtype="error_during_execution", result="bad")
    with pytest.raises(HeadlessCallError, match="error_during_execution"):
        parse_stream(stream, exit_code=0, stderr="")


@pytest.mark.parametrize(
    ("stdout", "reason"),
    [
        ("not json\n", "Line 1 of the output is not JSON"),
        (json.dumps(ISOLATED_INIT) + "\n", "no result event"),
        (json.dumps({"type": "result", "subtype": "success"}) + "\n", "no init event"),
    ],
)
def test_malformed_output_raises(stdout: str, reason: str) -> None:
    with pytest.raises(MalformedResponseError, match=reason):
        parse_stream(stdout, exit_code=0, stderr="")


def test_isolation_check_accepts_the_isolated_start_event() -> None:
    check_isolation(dict(ISOLATED_INIT), expected_model="sonnet")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tools", ["Bash"]),
        ("mcp_servers", [{"name": "x", "status": "connected"}]),
        ("plugins", [{"name": "caveman", "source": "caveman@user"}]),
        ("slash_commands", ["review"]),
        ("skills", ["deploy"]),
        ("agents", ["Explore"]),
        ("apiKeySource", "ANTHROPIC_API_KEY"),
    ],
)
def test_isolation_check_refuses_any_loaded_customisation(field: str, value: Any) -> None:
    init = dict(ISOLATED_INIT)
    init[field] = value
    with pytest.raises(IsolationError, match=field):
        check_isolation(init, expected_model="sonnet")


def test_isolation_check_refuses_the_wrong_model_family() -> None:
    with pytest.raises(IsolationError, match="model"):
        check_isolation(dict(ISOLATED_INIT), expected_model="opus")


def test_isolation_check_accepts_a_full_model_name() -> None:
    check_isolation(dict(ISOLATED_INIT), expected_model="claude-sonnet-5-5")


def test_subprocess_runner_turns_a_timeout_into_a_named_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _slow(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"], stderr=b"late")

    monkeypatch.setattr(subprocess, "run", _slow)
    with pytest.raises(HeadlessTimeoutError, match="did not finish within 3.0 s"):
        SubprocessRunner().run(["claude"], stdin="hi", env={}, cwd="/", timeout=3.0)


def test_subprocess_runner_passes_stdin_and_no_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def _fake(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen.update(kwargs, argv=argv)
        return subprocess.CompletedProcess(argv, 0, stdout=b"out", stderr=b"err")

    monkeypatch.setattr(subprocess, "run", _fake)
    raw = SubprocessRunner().run(
        ["claude", "-p"], stdin="prompt", env={"A": "1"}, cwd="/", timeout=5
    )
    assert (raw.exit_code, raw.stdout, raw.stderr) == (0, "out", "err")
    assert seen["input"] == b"prompt"
    assert seen["env"] == {"A": "1"}
    assert seen.get("shell", False) is False
    assert seen["timeout"] == 5


class _FakeProcess:
    def __init__(self, *, hang: bool) -> None:
        self.hang = hang
        self.killed = False
        self.returncode: int | None = None

    async def communicate(self, data: bytes) -> tuple[bytes, bytes]:
        if self.hang:
            await asyncio.sleep(10)
        self.returncode = 0
        return b"out:" + data, b""

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.returncode = -9
        return -9


def test_async_runner_kills_the_process_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _FakeProcess(hang=True)

    async def _spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)
    with pytest.raises(HeadlessTimeoutError):
        asyncio.run(SubprocessRunner().arun(["claude"], stdin="x", env={}, cwd="/", timeout=0.05))
    assert process.killed


def test_async_runner_returns_the_output(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        return _FakeProcess(hang=False)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)
    raw = asyncio.run(SubprocessRunner().arun(["claude"], stdin="x", env={}, cwd="/", timeout=1))
    assert (raw.exit_code, raw.stdout) == (0, "out:x")


def test_resolve_claude_names_a_missing_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(HeadlessCallError, match="Claude Code was not found as 'claude'"):
        resolve_claude("claude")


def test_resolve_claude_returns_an_absolute_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/opt/bin/claude")
    assert resolve_claude("claude") == "/opt/bin/claude"


def test_the_schema_tool_is_allowed_only_with_a_schema() -> None:
    init = {**ISOLATED_INIT, "tools": ["StructuredOutput"]}
    check_isolation(init, expected_model="sonnet", has_schema=True)
    with pytest.raises(IsolationError, match="StructuredOutput"):
        check_isolation(init, expected_model="sonnet")
    with pytest.raises(IsolationError, match="Bash"):
        check_isolation(
            {**ISOLATED_INIT, "tools": ["StructuredOutput", "Bash"]},
            expected_model="sonnet",
            has_schema=True,
        )
