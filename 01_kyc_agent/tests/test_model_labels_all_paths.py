"""Every way the engines call a model carries the model's labels, and none reaches the prompt.

The engines call a model three ways: ``invoke``, ``bind_tools`` and ``with_structured_output``.
The last two give a runnable built on the adapter's own model, so the labels set on the topic's
model have to reach that one as well. The adapter runs here for real on a scripted ``claude -p``.
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.tracers import BaseTracer
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fsi_common" / "tests" / "model"))

from model_test_support import FakeRunner, make_stream, schema_of  # noqa: E402

from utils.models import ROLE_MODELS, get_model  # noqa: E402

ROLE = "extract"
TOPIC = "01-kyc-onboarding"
PATHS = ("invoke", "bind_tools", "with_structured_output")


class Verdict(BaseModel):
    """A verdict, as a tool call and as a structured answer."""

    sound: bool


class Collector(BaseTracer):
    """Keeps every model run as it starts, whether it is a root run or a step of a chain."""

    def __init__(self) -> None:
        super().__init__()
        self.model_runs: list[Any] = []

    def _persist_run(self, run: Any) -> None:
        return

    def _on_run_create(self, run: Any) -> None:
        if run.run_type == "llm":
            self.model_runs.append(run)


def _answer(call: Any) -> Any:
    from fsi_common.model.headless import RawRun

    init = {
        "type": "system",
        "subtype": "init",
        "cwd": "/tmp/labels-test",
        "model": ROLE_MODELS[ROLE].model,
        "tools": [],
        "mcp_servers": [],
        "plugins": [],
        "slash_commands": [],
        "skills": [],
        "agents": [],
        "apiKeySource": "none",
        "claude_code_version": "2.1.302",
    }
    schema = schema_of(call)
    if schema is None:
        return RawRun(0, make_stream(result="done", init=init), "")
    name = schema["properties"]["tool_calls"]["items"]["anyOf"][0]["properties"]["name"]["const"]
    payload = {"content": "", "tool_calls": [{"name": name, "args": {"sound": True}}]}
    return RawRun(
        0, make_stream(structured=payload, init={**init, "tools": ["StructuredOutput"]}), ""
    )


@pytest.fixture()
def scripted(model_env, monkeypatch, tmp_path):
    """The real adapter on a scripted ``claude -p``, recording into a temporary folder."""
    import fsi_common.model as adapter

    runner = FakeRunner(_answer)
    make = adapter.make_chat_model
    monkeypatch.setattr(
        adapter,
        "make_chat_model",
        lambda **kwargs: make(**kwargs).model_copy(update={"runner": runner}),
    )
    model_env.setenv("MODEL_BACKEND", "record")
    model_env.setenv("MODEL_RECORDINGS_DIR", str(tmp_path))
    return runner


def _call(path: str, collector: Collector) -> None:
    config = {"callbacks": [collector], "metadata": {"thread_id": "thread-LABEL-1"}}
    model = get_model(ROLE)
    if path == "invoke":
        model.invoke("Read the paragraph.", config=config)
    elif path == "bind_tools":
        model.bind_tools([Verdict]).invoke("Read the paragraph.", config=config)
    else:
        model.with_structured_output(Verdict, method="json_schema").invoke(
            "Read the paragraph.", config=config
        )


@pytest.mark.parametrize("path", PATHS)
def test_the_model_run_carries_the_models_labels_on_every_call_path(scripted, path):
    collector = Collector()
    _call(path, collector)
    (run,) = collector.model_runs
    chosen = ROLE_MODELS[ROLE]
    metadata = run.extra["metadata"]
    assert metadata["topic"] == TOPIC
    assert metadata["model_role"] == ROLE
    assert metadata["model_name"] == chosen.model
    assert metadata["model_effort"] == chosen.effort
    assert {f"topic:{TOPIC}", f"role:{ROLE}"} <= set(run.tags)


@pytest.mark.parametrize("path", PATHS)
def test_no_label_reaches_the_prompt_the_model_is_sent(scripted, path):
    _call(path, Collector())
    (call,) = scripted.calls
    sent = json.dumps([call.argv, call.stdin])
    for label in (TOPIC, "model_role", f"role:{ROLE}", "thread-LABEL-1", "topic:"):
        assert label not in sent
