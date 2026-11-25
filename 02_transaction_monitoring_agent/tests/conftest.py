"""Shared fixtures for topic 02's tests: a clean model environment and a fake model adapter.

Tests never trace and never call a model: tracing is switched off before any topic module is
imported, and the adapter ``fsi_common.model`` is replaced by a fake wherever a test needs it.
This file holds fixtures only; the fakes a test imports by name live in ``model_fakes``, because
every member's ``conftest`` is importable under the one name ``conftest``.
"""

import os
import sys
import types
from typing import Any

import pytest
from model_fakes import FakeChatModel, FakeReplayMissError

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
