"""Tests for the chat model over headless Claude Code, run entirely on a fake subprocess."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from model_test_support import (
    ISOLATED_INIT,
    USAGE,
    FakeCall,
    FakeRunner,
    envelope_reply,
    flag_value,
    make_stream,
    schema_of,
    text_reply,
)
from pydantic import BaseModel, Field

from fsi_common.model import (
    ChatClaudeHeadless,
    HeadlessCallError,
    IsolationError,
    MalformedResponseError,
    ModelConfigError,
    ReplayMissError,
    call_records,
    make_chat_model,
    reset_call_records,
)
from fsi_common.model import gate as gate_module
from fsi_common.model.headless import RawRun


class Obligation(BaseModel):
    """Something a firm must do under the document."""

    requirement: str = Field(description="What the firm must do")
    paragraph: str = Field(description="The paragraph number")
    deadline: str | None = Field(description="The deadline as written, or null")
    evidence: str = Field(description="A word-for-word quote")


class SectionSummary(BaseModel):
    """A summary of one section of the document."""

    number: str
    title: str
    summary: str
    obligations: list[Obligation]


SUMMARY_ARGS = {
    "number": "7",
    "title": "Incident reporting",
    "summary": "Firms report incidents.",
    "obligations": [
        {
            "requirement": "Report major incidents",
            "paragraph": "7.1",
            "deadline": "within 4 hours",
            "evidence": "Firms must notify the FSOA of a major incident within 4 hours",
        }
    ],
}


@tool
def get_document(document_id: str) -> dict:
    """A document in the library, as a JSON object with its sections."""
    return {"document_id": document_id, "sections": []}


def _model(tmp_path: Path, runner: FakeRunner, **overrides: Any) -> ChatClaudeHeadless:
    values: dict[str, Any] = {
        "model": "sonnet",
        "effort": "low",
        "mode": "live",
        "recordings_dir": tmp_path / "recordings",
    }
    values.update(overrides)
    chat = make_chat_model(**values)
    return chat.model_copy(update={"runner": runner})


@pytest.fixture(autouse=True)
def _clean_records() -> None:
    reset_call_records()


def test_make_chat_model_validates_its_arguments(tmp_path: Path) -> None:
    good = {"model": "sonnet", "effort": None, "mode": "live", "recordings_dir": tmp_path}
    assert isinstance(make_chat_model(**good), ChatClaudeHeadless)
    with pytest.raises(ModelConfigError, match="mode must be one of"):
        make_chat_model(**{**good, "mode": "cached"})
    with pytest.raises(ModelConfigError, match="max_concurrency must be between 1 and 4"):
        make_chat_model(**good, max_concurrency=5)
    with pytest.raises(ModelConfigError, match="effort must be one of"):
        make_chat_model(**{**good, "effort": "huge"})


def test_plain_invoke_sends_prompt_on_stdin_and_fills_usage(tmp_path: Path, fake_runner) -> None:
    runner = fake_runner(text_reply("OK"))
    reply = _model(tmp_path, runner).invoke([SystemMessage("Be brief."), HumanMessage("Say OK")])
    assert isinstance(reply, AIMessage)
    assert reply.content == "OK"
    assert reply.tool_calls == []
    assert reply.usage_metadata == {
        "input_tokens": 160,
        "output_tokens": 7,
        "total_tokens": 167,
        "input_token_details": {"cache_read": 50, "cache_creation": 100},
    }
    assert reply.response_metadata["mode"] == "live"
    assert len(reply.response_metadata["request_hash"]) == 64
    (call,) = runner.calls
    assert call.stdin == "Say OK"
    assert flag_value(call.argv, "--system-prompt").startswith("Be brief.")
    assert schema_of(call) is None


def test_bound_tools_return_tool_calls_with_minted_ids(tmp_path: Path, fake_runner) -> None:
    calls = [
        {"name": "get_document", "args": {"document_id": "PS26-4"}},
        {"name": "get_document", "args": {"document_id": "PS26-4"}},
    ]
    runner = fake_runner(envelope_reply("Loading.", calls))
    bound = _model(tmp_path, runner).bind_tools([get_document])
    first = bound.invoke("Load PS26-4")
    second = bound.invoke("Load PS26-4")
    assert first.content == "Loading."
    assert [c["name"] for c in first.tool_calls] == ["get_document", "get_document"]
    ids = [c["id"] for c in first.tool_calls]
    assert len(set(ids)) == 2
    assert ids == [c["id"] for c in second.tool_calls]
    schema = schema_of(runner.calls[0])
    assert schema["properties"]["tool_calls"]["items"]["anyOf"][0]["properties"]["name"] == {
        "const": "get_document"
    }


def test_structured_output_forces_the_schema_tool(tmp_path: Path, fake_runner) -> None:
    runner = fake_runner(envelope_reply("", [{"name": "SectionSummary", "args": SUMMARY_ARGS}]))
    structured = _model(tmp_path, runner).with_structured_output(SectionSummary)
    summary = structured.invoke("Section 7: Incident reporting\n\n7.1 Firms must ...")
    assert isinstance(summary, SectionSummary)
    assert summary.obligations[0].deadline == "within 4 hours"
    tool_calls = schema_of(runner.calls[0])["properties"]["tool_calls"]
    assert tool_calls["minItems"] == 1


def test_history_with_tool_results_reaches_the_prompt(tmp_path: Path, fake_runner) -> None:
    runner = fake_runner(envelope_reply("Done.", []))
    history = [
        HumanMessage("Load PS26-4"),
        AIMessage(
            "", tool_calls=[{"name": "get_document", "args": {"document_id": "X"}, "id": "c1"}]
        ),
        ToolMessage('{"title": "PS26-4"}', tool_call_id="c1", name="get_document"),
    ]
    _model(tmp_path, runner).bind_tools([get_document]).invoke(history)
    assert '<message role="tool" tool_call_id="c1" name="get_document">' in runner.calls[0].stdin


def test_record_then_replay_reproduces_the_call_without_the_runner(
    tmp_path: Path, fake_runner
) -> None:
    runner = fake_runner(
        envelope_reply("Loading.", [{"name": "get_document", "args": {"document_id": "X"}}])
    )
    recorded = _model(tmp_path, runner, mode="record").bind_tools([get_document]).invoke("Load X")
    files = list((tmp_path / "recordings").glob("*.json"))
    assert len(files) == 1
    silent = fake_runner(text_reply("must not be called"))
    replayed = _model(tmp_path, silent, mode="replay").bind_tools([get_document]).invoke("Load X")
    assert silent.calls == []
    assert replayed.content == recorded.content
    assert replayed.tool_calls == recorded.tool_calls
    assert replayed.usage_metadata == recorded.usage_metadata
    assert replayed.response_metadata["mode"] == "replay"
    assert recorded.response_metadata["mode"] == "record"
    stored = json.loads(files[0].read_text(encoding="utf-8"))
    assert stored["meta"]["init"]["tools"] == ["StructuredOutput"]


def test_a_recording_keeps_no_account_state_or_cost(tmp_path: Path, fake_runner) -> None:
    usage = {
        **USAGE,
        "service_tier": "standard",
        "inference_geo": "global",
        "fallback_credit": None,
        "speed": "standard",
        "cache_creation": {"ephemeral_1h_input_tokens": 100},
        "server_tool_use": {"web_search_requests": 0},
        "iterations": [{"input_tokens": 10}],
    }
    limit = {"type": "rate_limit_event", "rate_limit_info": {"utilization": 0.46}}
    lines = make_stream(result="Hi", usage=usage).splitlines()
    stream = "\n".join([lines[0], json.dumps(limit), *lines[1:]]) + "\n"
    runner = fake_runner(lambda call: RawRun(0, stream, ""))
    recorded = _model(tmp_path, runner, mode="record").invoke("Hi")
    (path,) = (tmp_path / "recordings").glob("*.json")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert sorted(stored) == ["meta", "request", "request_sha256", "response"]
    assert sorted(stored["meta"]) == ["duration_s", "init", "recorded_at"]
    assert sorted(stored["meta"]["init"]) == [
        "agents",
        "apiKeySource",
        "claude_code_version",
        "mcp_servers",
        "model",
        "plugins",
        "skills",
        "slash_commands",
        "tools",
    ]
    assert sorted(stored["response"]) == ["content", "model_reported", "tool_calls", "usage"]
    assert stored["response"]["usage"] == USAGE
    text = path.read_text(encoding="utf-8")
    for word in ("rate_limit", "utilization", "cost", "overage", "service_tier", "geo"):
        assert word not in text
    replayed = _model(tmp_path, fake_runner(text_reply("unused")), mode="replay").invoke("Hi")
    for reply in (recorded, replayed):
        assert set(reply.response_metadata) == {"mode", "request_hash", "model_name"}


def test_replay_miss_names_the_hash_and_never_calls(tmp_path: Path, fake_runner) -> None:
    silent = fake_runner(text_reply("must not be called"))
    with pytest.raises(ReplayMissError) as caught:
        _model(tmp_path, silent, mode="replay").invoke("Never recorded")
    assert len(caught.value.request_hash) == 64
    assert caught.value.request_hash in str(caught.value)
    assert silent.calls == []


def test_live_mode_writes_no_recording(tmp_path: Path, fake_runner) -> None:
    _model(tmp_path, fake_runner(text_reply("OK"))).invoke("Hi")
    assert not (tmp_path / "recordings").exists()


def test_a_failed_call_raises_with_exit_code(tmp_path: Path, fake_runner) -> None:
    runner = fake_runner(lambda call: RawRun(1, "", "Error: not signed in"))
    with pytest.raises(HeadlessCallError, match="not signed in") as caught:
        _model(tmp_path, runner).invoke("Hi")
    assert caught.value.exit_code == 1


def test_a_missing_envelope_raises(tmp_path: Path, fake_runner) -> None:
    runner = fake_runner(text_reply("I will not use JSON"))
    with pytest.raises(MalformedResponseError, match="no structured output"):
        _model(tmp_path, runner).bind_tools([get_document]).invoke("Load X")


def test_a_call_that_loaded_customisations_is_refused(tmp_path: Path, fake_runner) -> None:
    leaky = {**ISOLATED_INIT, "tools": ["Bash", "Read"]}
    runner = fake_runner(lambda call: RawRun(0, make_stream(result="OK", init=leaky), ""))
    with pytest.raises(IsolationError, match="tools"):
        _model(tmp_path, runner, mode="record").invoke("Hi")
    assert not (tmp_path / "recordings").exists()


def test_stop_sequences_are_refused(tmp_path: Path, fake_runner) -> None:
    with pytest.raises(ModelConfigError, match="stop sequences"):
        _model(tmp_path, fake_runner(text_reply("OK"))).invoke("Hi", stop=["\n"])


def test_threads_share_the_process_cap(tmp_path: Path, fake_runner) -> None:
    runner = fake_runner(text_reply("OK"), delay_s=0.05)
    chat = _model(tmp_path, runner)
    threads = [threading.Thread(target=chat.invoke, args=(f"call {i}",)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(runner.calls) == 10
    assert gate_module.process_gate().peak == 4
    records = call_records()
    assert len(records) == 10
    assert max(r.in_flight_at_start for r in records) == 4
    assert all(r.mode == "live" and r.duration_s >= 0.05 for r in records)


def test_two_models_cannot_exceed_the_process_cap_together(tmp_path: Path, fake_runner) -> None:
    runner = fake_runner(text_reply("OK"), delay_s=0.05)
    first = _model(tmp_path, runner, max_concurrency=3)
    second = _model(tmp_path, runner, max_concurrency=3)
    threads = [
        threading.Thread(target=(first if i % 2 else second).invoke, args=(f"call {i}",))
        for i in range(12)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert gate_module.process_gate().peak == 4


def test_ainvoke_runs_on_the_event_loop_under_the_cap(tmp_path: Path, fake_runner) -> None:
    runner = fake_runner(text_reply("OK"), delay_s=0.05)
    chat = _model(tmp_path, runner)

    async def main() -> list[AIMessage]:
        return await asyncio.gather(*(chat.ainvoke(f"call {i}") for i in range(8)))

    replies = asyncio.run(main())
    assert [r.content for r in replies] == ["OK"] * 8
    assert gate_module.process_gate().peak == 4


def _scripted(call: FakeCall) -> RawRun:
    """Answer like a model would for the starter's orchestrator and section sub-agents."""
    schema = schema_of(call)
    names = []
    if schema is not None:
        branches = schema["properties"]["tool_calls"]["items"]["anyOf"]
        names = [b["properties"]["name"]["const"] for b in branches]
    if "SectionSummary" in names:
        number = "1" if "Section 1" in call.stdin else "2"
        args = {**SUMMARY_ARGS, "number": number, "title": f"Title {number}"}
        payload = {"content": "", "tool_calls": [{"name": "SectionSummary", "args": args}]}
    elif "task" in names and 'name="task"' not in call.stdin:
        payload = {
            "content": "Fanning out.",
            "tool_calls": [
                {
                    "name": "task",
                    "args": {
                        "description": f"Section {n}: text",
                        "subagent_type": "section-summariser",
                    },
                }
                for n in (1, 2)
            ],
        }
    else:
        payload = {"content": "The brief.", "tool_calls": []}
    return RawRun(0, make_stream(structured=payload), "")


def test_a_deep_agent_runs_its_sub_agents_on_the_adapter(tmp_path: Path, fake_runner) -> None:
    from deepagents import create_deep_agent

    runner = fake_runner(_scripted)
    chat = _model(tmp_path, runner, mode="record")
    sub_agent = {
        "name": "section-summariser",
        "description": "Summarises ONE section. Returns a SectionSummary.",
        "system_prompt": "Return a SectionSummary.",
        "tools": [],
        "response_format": SectionSummary,
    }
    agent = create_deep_agent(
        model=chat, tools=[get_document], system_prompt="Orchestrate.", subagents=[sub_agent]
    )
    result = agent.invoke({"messages": [{"role": "user", "content": "Summarise PS26-4"}]})
    task_results = [m for m in result["messages"] if m.type == "tool" and m.name == "task"]
    summaries = [SectionSummary(**json.loads(m.content)) for m in task_results]
    assert sorted(s.number for s in summaries) == ["1", "2"]
    assert result["messages"][-1].text == "The brief."
    assert len(runner.calls) == 4

    silent = fake_runner(text_reply("must not be called"))
    replay = _model(tmp_path, silent, mode="replay")
    agent_again = create_deep_agent(
        model=replay, tools=[get_document], system_prompt="Orchestrate.", subagents=[sub_agent]
    )
    again = agent_again.invoke({"messages": [{"role": "user", "content": "Summarise PS26-4"}]})
    assert silent.calls == []
    assert again["messages"][-1].text == "The brief."


def test_a_structured_response_agent_returns_the_model(tmp_path: Path, fake_runner) -> None:
    from deepagents import create_deep_agent

    runner = fake_runner(_scripted)
    summariser = create_deep_agent(
        model=_model(tmp_path, runner),
        system_prompt="Return a SectionSummary.",
        response_format=SectionSummary,
    )
    out = summariser.invoke({"messages": [{"role": "user", "content": "Section 1: text"}]})
    assert isinstance(out["structured_response"], SectionSummary)
    assert out["structured_response"].number == "1"
