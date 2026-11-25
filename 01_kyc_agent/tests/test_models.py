"""Tests of get_model(role): every role on every backend, the deferred model, and the refusals."""

import sys
from pathlib import Path

import pytest
from model_fakes import FakeChatModel, FakeReplayMissError

from utils import models
from utils.models import (
    BACKENDS,
    ROLE_MODELS,
    DeferredChatModel,
    ModelAdapterMissingError,
    ModelConfigError,
    TracingKeyMissingError,
    get_model,
)

LABEL_KEYS = ("topic", "topic_number", "model_role", "model_name", "model_effort")
ADAPTER_BACKENDS = {"claude-code": "live", "record": "record", "replay": "replay"}


def test_the_roles_are_the_two_the_topic_uses():
    assert set(ROLE_MODELS) == {"extract", "memo"}


def test_reading_runs_on_sonnet_and_writing_on_opus():
    assert "sonnet" in ROLE_MODELS["extract"].model
    assert "opus" in ROLE_MODELS["memo"].model


@pytest.mark.parametrize("role", sorted(ROLE_MODELS))
@pytest.mark.parametrize(("backend", "mode"), sorted(ADAPTER_BACKENDS.items()))
def test_every_role_on_every_adapter_backend(
    model_env, fake_adapter, role, backend, mode, tmp_path
):
    model_env.setenv("MODEL_BACKEND", backend)
    model_env.setenv("MODEL_RECORDINGS_DIR", str(tmp_path))
    chat = get_model(role)
    assert isinstance(chat, DeferredChatModel)
    assert fake_adapter == []
    assert chat.invoke("hello").content == "fake reply"
    assert fake_adapter == [
        {
            "model": ROLE_MODELS[role].model,
            "effort": ROLE_MODELS[role].effort,
            "mode": mode,
            "recordings_dir": tmp_path,
            "max_concurrency": 4,
        }
    ]


@pytest.mark.parametrize("role", sorted(ROLE_MODELS))
def test_every_model_names_its_topic_role_model_and_effort_for_langsmith(model_env, role):
    chat = get_model(role)
    chosen = ROLE_MODELS[role]
    assert {key: chat.metadata[key] for key in LABEL_KEYS} == {
        "topic": "01-kyc-onboarding",
        "topic_number": "01",
        "model_role": role,
        "model_name": chosen.model,
        "model_effort": chosen.effort,
    }
    assert chat.tags == ["topic:01-kyc-onboarding", f"role:{role}"]


@pytest.mark.parametrize("role", sorted(ROLE_MODELS))
def test_every_role_on_the_langchain_backend(model_env, monkeypatch, role):
    model_env.setenv("MODEL_BACKEND", "langchain")
    model_env.setenv("MODEL_NAME", "anthropic:some-model")
    seen = []

    def fake_init_chat_model(name):
        seen.append(name)
        return FakeChatModel(calls=[])

    monkeypatch.setattr("langchain.chat_models.init_chat_model", fake_init_chat_model)
    assert isinstance(get_model(role), FakeChatModel)
    assert seen == ["anthropic:some-model"]


def test_the_default_backend_is_replay(model_env, fake_adapter):
    get_model("extract").invoke("hello")
    assert fake_adapter[0]["mode"] == "replay"


def test_the_model_is_built_once_and_reused(model_env, fake_adapter):
    chat = get_model("memo")
    chat.invoke("one")
    chat.invoke("two")
    assert len(fake_adapter) == 1
    assert len(chat.resolve().calls) == 2


def test_bind_tools_and_structured_output_go_to_the_adapter_model(model_env, fake_adapter):
    chat = get_model("extract")
    bound = chat.bind_tools(["a tool"], tool_choice="any")
    assert bound is chat.resolve()
    assert bound.bound == (["a tool"], {"tool_choice": "any"})
    assert chat.with_structured_output(dict).structured == (dict, {})


async def _ainvoke(chat):
    return await chat.ainvoke("hello")


def test_async_calls_go_to_the_adapter_model(model_env, fake_adapter):
    import asyncio

    assert asyncio.run(_ainvoke(get_model("memo"))).content == "fake reply"


def test_a_replay_miss_reaches_the_caller(model_env, fake_adapter, monkeypatch):
    def miss(self, messages, stop=None, run_manager=None, **kwargs):
        raise FakeReplayMissError("no recording for prompt hash 3f1c")

    monkeypatch.setattr(FakeChatModel, "_generate", miss)
    with pytest.raises(FakeReplayMissError, match="prompt hash 3f1c"):
        get_model("extract").invoke("hello")


def test_a_missing_adapter_fails_by_name_on_first_call(model_env, monkeypatch):
    monkeypatch.setitem(sys.modules, "fsi_common.model", None)
    chat = get_model("extract")
    with pytest.raises(ModelAdapterMissingError, match="fsi_common.model for role 'extract'"):
        chat.invoke("hello")


def test_an_unknown_role_is_refused(model_env):
    with pytest.raises(ModelConfigError, match="There is no model role 'writer'"):
        get_model("writer")


def test_an_unknown_backend_is_refused(model_env):
    model_env.setenv("MODEL_BACKEND", "openai")
    with pytest.raises(ModelConfigError, match="MODEL_BACKEND is 'openai'"):
        get_model("extract")


@pytest.mark.parametrize("flag", ["LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"])
@pytest.mark.parametrize("backend", BACKENDS)
def test_tracing_with_an_empty_key_is_refused(model_env, flag, backend):
    model_env.setenv("MODEL_BACKEND", backend)
    model_env.setenv(flag, "True")
    model_env.setenv("LANGSMITH_API_KEY", "  ")
    with pytest.raises(TracingKeyMissingError, match="LANGSMITH_API_KEY is empty"):
        get_model("extract")


def test_the_tracing_refusal_names_both_ways_out(model_env):
    model_env.setenv("LANGSMITH_TRACING", "true")
    with pytest.raises(TracingKeyMissingError) as exc_info:
        get_model("extract")
    message = str(exc_info.value)
    assert "export LANGSMITH_KEY in your shell" in message
    assert "set LANGSMITH_TRACING=false in the .env in the repository root" in message


def test_tracing_with_a_key_is_allowed(model_env, fake_adapter):
    model_env.setenv("LANGSMITH_TRACING", "true")
    model_env.setenv("LANGSMITH_API_KEY", "a-key-for-the-test")
    assert isinstance(get_model("extract"), DeferredChatModel)


def test_tracing_off_needs_no_key(model_env, fake_adapter):
    model_env.setenv("LANGSMITH_TRACING", "false")
    assert isinstance(get_model("extract"), DeferredChatModel)


def test_recordings_dir_default_and_relative(model_env):
    assert models.recordings_dir({}) == models.PROJECT_ROOT / "recordings"
    relative = models.recordings_dir({"MODEL_RECORDINGS_DIR": "01_kyc_agent/rec"})
    assert relative == models.REPO_ROOT / "01_kyc_agent" / "rec"
    assert models.recordings_dir({"MODEL_RECORDINGS_DIR": "/tmp/rec"}) == Path("/tmp/rec")


def test_the_starter_model_name_is_still_exported():
    assert isinstance(models.model, str)
    assert ":" in models.model
