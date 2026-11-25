"""Fixtures for the tracing helpers' tests: the model adapter's fake runner, no real processes."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_MODEL_TESTS = Path(__file__).resolve().parents[1] / "model"
if str(_MODEL_TESTS) not in sys.path:
    sys.path.insert(0, str(_MODEL_TESTS))


@pytest.fixture(autouse=True)
def _no_real_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that would start a real process."""

    def _refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"a test tried to start a real process: {args!r}")

    monkeypatch.setattr(subprocess, "run", _refuse)
    monkeypatch.setattr(subprocess, "Popen", _refuse)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _refuse)
