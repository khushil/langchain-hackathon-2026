"""Labels travel beside a model request and never in it: the recording key does not move."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tracers import BaseTracer
from model_test_support import FakeRunner, text_reply

from fsi_common.model import make_chat_model, reset_call_records
from fsi_common.tracing import model_labels, run_labels


class _Collector(BaseTracer):
    """Keeps every finished run, so a test can read the labels a model run carried."""

    def __init__(self) -> None:
        super().__init__()
        self.finished: list[Any] = []

    def _persist_run(self, run: Any) -> None:
        self.finished.append(run)


@pytest.fixture(autouse=True)
def _clean_records() -> None:
    reset_call_records()


def _model(folder: Path, runner: FakeRunner, **extra: Any) -> Any:
    chat = make_chat_model(
        model="sonnet", effort="low", mode="record", recordings_dir=folder
    ).model_copy(update={"runner": runner, **extra})
    return chat


MESSAGES = [
    SystemMessage("Read the paragraph."),
    HumanMessage("Paragraph 4.1 says the firm must act."),
]


def test_the_request_hash_is_the_same_with_labels_as_without(tmp_path: Path) -> None:
    plain = _model(tmp_path / "plain", FakeRunner(text_reply("done")))
    labels = model_labels("brief", "section", model="sonnet", effort="low")
    run = run_labels("brief", "t-1", {"document_id": "D", "firm_id": "F"})
    labelled = _model(
        tmp_path / "labelled",
        FakeRunner(text_reply("done")),
        metadata=labels.metadata,
        tags=labels.tags,
    )
    plain.invoke(MESSAGES)
    labelled.invoke(
        MESSAGES, config={"metadata": run.metadata, "tags": run.tags, "run_name": "section"}
    )
    plain_files = sorted(p.name for p in (tmp_path / "plain").glob("*.json"))
    labelled_files = sorted(p.name for p in (tmp_path / "labelled").glob("*.json"))
    assert plain_files and plain_files == labelled_files


def test_the_stored_request_holds_no_label(tmp_path: Path) -> None:
    labels = model_labels("brief", "section", model="sonnet", effort="low")
    run = run_labels("brief", "t-1", {"document_id": "UNIQUE-DOC-9", "firm_id": "UNIQUE-FIRM-9"})
    chat = _model(
        tmp_path, FakeRunner(text_reply("done")), metadata=labels.metadata, tags=labels.tags
    )
    chat.invoke(MESSAGES, config={"metadata": run.metadata, "tags": run.tags})
    (path,) = tmp_path.glob("*.json")
    stored = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(stored["request"])
    for forbidden in ("UNIQUE-DOC-9", "UNIQUE-FIRM-9", "topic:03", "03-compliance-brief", "t-1"):
        assert forbidden not in text


def test_a_recording_made_without_labels_replays_with_them(tmp_path: Path) -> None:
    _model(tmp_path, FakeRunner(text_reply("done"))).invoke(MESSAGES)
    labels = model_labels("brief", "section", model="sonnet", effort="low")
    run = run_labels("brief", "t-1", {"document_id": "D"})
    silent = FakeRunner(text_reply("must not be called"))
    replayer = make_chat_model(
        model="sonnet", effort="low", mode="replay", recordings_dir=tmp_path
    ).model_copy(update={"runner": silent, "metadata": labels.metadata, "tags": labels.tags})
    reply = replayer.invoke(MESSAGES, config={"metadata": run.metadata, "tags": run.tags})
    assert reply.content == "done"
    assert silent.calls == []


def test_the_labels_do_reach_the_model_run(tmp_path: Path) -> None:
    labels = model_labels("brief", "section", model="sonnet", effort="low")
    run = run_labels("brief", "t-1", {"document_id": "D", "firm_id": "F"})
    collector = _Collector()
    chat = _model(
        tmp_path, FakeRunner(text_reply("done")), metadata=labels.metadata, tags=labels.tags
    )
    chat.invoke(
        MESSAGES,
        config={"metadata": run.metadata, "tags": run.tags, "callbacks": [collector]},
    )
    (traced,) = collector.finished
    assert traced.extra["metadata"]["topic"] == "03-compliance-brief"
    assert traced.extra["metadata"]["document_id"] == "D"
    assert traced.extra["metadata"]["model_role"] == "section"
    assert traced.extra["metadata"]["thread_id"] == "t-1"
    assert {"topic:03-compliance-brief", "document:D", "institution:F", "role:section"} <= set(
        traced.tags
    )


def test_no_label_reaches_the_prompt_the_model_is_sent(tmp_path: Path) -> None:
    labels = model_labels("brief", "section", model="sonnet", effort="low")
    run = run_labels(
        "brief", "thread-LABEL-1", {"document_id": "DOC-LABEL-1", "firm_id": "F-LABEL"}
    )
    runner = FakeRunner(text_reply("done"))
    chat = _model(tmp_path, runner, metadata=labels.metadata, tags=labels.tags)
    chat.invoke(MESSAGES, config={"metadata": run.metadata, "tags": run.tags})
    (call,) = runner.calls
    sent = json.dumps([call.argv, call.stdin])
    for label in (
        "thread-LABEL-1",
        "DOC-LABEL-1",
        "F-LABEL",
        "03-compliance-brief",
        "model_role",
        "model_effort",
        "topic:",
        "role:section",
        "stage:review",
    ):
        assert label not in sent
