"""Fixtures for the model adapter's tests: a fake headless runner and a ban on real processes."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
for _path in (_HERE.parents[1], _HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from model_test_support import FakeRunner, Responder  # noqa: E402

from fsi_common.model import gate as gate_module  # noqa: E402

LIVE_ENV = "FSI_LIVE_MODEL_TESTS"


def pytest_configure(config: pytest.Config) -> None:
    """Register the `live` marker for tests that make a real headless call."""
    config.addinivalue_line("markers", "live: makes one real headless call; skipped by default")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip live tests unless the environment opts in, so the default suite spends nothing."""
    import os

    if os.environ.get(LIVE_ENV) == "1":
        return
    skip = pytest.mark.skip(reason=f"live headless call; set {LIVE_ENV}=1 to run it")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _no_real_subprocess(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that would start a real process, so no test spends the usage meter."""
    if request.node.get_closest_marker("live"):
        return

    def _refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"a test tried to start a real process: {args!r}")

    monkeypatch.setattr(subprocess, "run", _refuse)
    monkeypatch.setattr(subprocess, "Popen", _refuse)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _refuse)


@pytest.fixture(autouse=True)
def _fresh_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test its own process gate, so peaks from one test never leak into another."""
    monkeypatch.setattr(gate_module, "_PROCESS_GATE", gate_module.ConcurrencyGate(4))


@pytest.fixture
def fake_runner() -> Callable[..., FakeRunner]:
    """Build a fake runner from a responder."""

    def _build(responder: Responder, *, delay_s: float = 0.0) -> FakeRunner:
        return FakeRunner(responder=responder, delay_s=delay_s)

    return _build
