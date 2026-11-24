"""Shared fixtures for topic 03's tests: a clean model environment and a fake model adapter.

Tests never trace and never call a model: tracing is switched off before any topic module is
imported, and the adapter ``fsi_common.model`` is replaced by a fake wherever a test needs it.
"""

import os
import sys
import types
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["MODEL_BACKEND"] = "replay"

MODEL_ENV = (
    "MODEL_BACKEND",
    "MODEL_NAME",
    "MODEL_RECORDINGS_DIR",
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING_V2",
    "LANGSMITH_API_KEY",
    "LANGCHAIN_API_KEY",
)


class FakeChatModel(BaseChatModel):
    """A chat model that answers every call with one fixed reply and records what it was given."""

    reply: str = "fake reply"
    calls: list[Any] = []
    bound: Any = None
    structured: Any = None

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.reply))])

    def bind_tools(self, tools, **kwargs):
        self.bound = (tools, kwargs)
        return self

    def with_structured_output(self, schema, **kwargs):
        self.structured = (schema, kwargs)
        return self


class FakeReplayMissError(Exception):
    """Stands in for the adapter's ReplayMissError."""


@pytest.fixture()
def model_env(monkeypatch):
    """Clear every model and tracing setting, so each test states the ones it needs."""
    for name in MODEL_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture()
def fake_adapter(monkeypatch):
    """Install a fake ``fsi_common.model`` and return the list of calls to its factory."""
    made: list[dict[str, Any]] = []
    module = types.ModuleType("fsi_common.model")

    def make_chat_model(**kwargs):
        made.append(kwargs)
        return FakeChatModel(calls=[])

    module.make_chat_model = make_chat_model
    module.ReplayMissError = FakeReplayMissError
    monkeypatch.setitem(sys.modules, "fsi_common.model", module)
    return made
