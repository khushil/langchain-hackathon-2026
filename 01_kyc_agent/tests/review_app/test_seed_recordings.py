"""The starting work comes from the recordings on any server; a seed stopped partway finishes."""

import json
import os
import stat
from pathlib import Path

import pytest
from kyc_fakes import ScriptedReader
from starlette.testclient import TestClient
from support import REQUEST_TEXT

from fsi_common.app import AppConfig, SeedError, create_app
from fsi_common.app.session import SessionCodec
from review_app import seed, service
from review_app.context import Services
from review_app.plugin import NAME, build_plugin
from workflow.runs import KycRuns


def wait_until(runs, thread: str, wanted: set[str] | None = None, seconds: float = 30.0) -> str:
    import time

    wanted = wanted or {"awaiting_review"}
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if runs.status(thread) in wanted:
            return thread
        time.sleep(0.02)
    raise AssertionError(f"run {thread} is {runs.status(thread)}")


@pytest.fixture()
def stand_in(tmp_path, monkeypatch):
    """Put a stand-in ``claude`` first on PATH that logs each start and refuses it."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "claude-calls.log"
    program = bin_dir / "claude"
    program.write_text(f'#!/bin/sh\necho "called" >> "{log}"\nexit 3\n')
    program.chmod(program.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("MODEL_BACKEND", "claude-code")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    service.use_models(None)
    return log


def calls(log: Path) -> list[str]:
    return log.read_text().split() if log.exists() else []


def start(folder: Path, services: Services | None = None) -> tuple[Services, object]:
    services = services or Services()
    config = AppConfig(secret=b"s", topic_folders=(), state_dir=folder, seed=NAME)
    return services, create_app(config, topics=[build_plugin(services)])


def close(services: Services) -> None:
    services.runs().close()
    services.drafts.close()


def statuses(services: Services) -> list[str]:
    runs = services.runs()
    return sorted(runs.status(t) for t in runs.list_runs())


def test_the_stand_in_catches_a_live_call_when_one_is_made(stand_in):
    from utils.models import get_model

    with pytest.raises(Exception, match="claude|Claude|exit"):
        get_model("extract").invoke("hello")
    assert calls(stand_in) == ["called"]


def test_a_server_on_a_live_backend_seeds_from_the_recordings_and_calls_no_model(
    tmp_path, stand_in
):
    services, _ = start(tmp_path / "state")
    try:
        assert statuses(services) == ["awaiting_review", "signed"]
        assert calls(stand_in) == []
        assert os.environ["MODEL_BACKEND"] == "claude-code"
    finally:
        close(services)


def test_a_batch_started_after_the_seed_on_a_live_backend_still_calls_the_model(tmp_path, stand_in):
    services, app = start(tmp_path / "state")
    try:
        client = TestClient(app, follow_redirects=True)
        client.cookies.set(app.state.cookie_name, SessionCodec(b"s").encode(seed.REVIEWER))
        client.post("/kyc/runs", data={"customers": ["CUST-001"]})
        runs = services.runs()
        thread = next(t for t in runs.list_runs() if runs.status(t) in {"running", "failed"})
        wait_until(runs, thread, {"awaiting_review", "failed"})
        assert calls(stand_in), "outside the seed the server's own backend is used"
    finally:
        close(services)


def stop_after(monkeypatch, name: str, times: int) -> None:
    """Make a function of the seed raise ``SeedError`` after it has run ``times`` times."""
    real, count = getattr(seed, name), {"n": 0}

    def stopped(*args, **kwargs):
        count["n"] += 1
        if count["n"] > times:
            raise SeedError("stopped for the test")
        return real(*args, **kwargs)

    monkeypatch.setattr(seed, name, stopped)


@pytest.mark.parametrize(
    ("function", "times", "expected_runs"),
    [
        ("_start_and_wait", 1, 1),  # stopped with the waiting batch made
        ("_expect_redirect", 11, 2),  # stopped in the middle of the signed batch's decisions
        ("_write_marker", 0, 2),  # stopped after the signing, before the marker
    ],
)
def test_a_seed_stopped_partway_finishes_on_the_next_start_without_a_second_copy(
    tmp_path, monkeypatch, function, times, expected_runs
):
    folder = tmp_path / "state"
    stopped_services = Services()
    with monkeypatch.context() as stopped:
        stop_after(stopped, function, times)
        with pytest.raises(SeedError, match="stopped for the test"):
            start(folder, stopped_services)
    assert len(stopped_services.runs().list_runs()) == expected_runs
    close(stopped_services)
    services, _ = start(folder)
    try:
        assert statuses(services) == ["awaiting_review", "signed"]
        signed = next(
            t for t in services.runs().list_runs() if services.runs().status(t) == "signed"
        )
        state = services.runs().result(signed)
        assert len(state["decisions"]) == 37 and len(state["sign_off"]["assumptions"]) == 2
        assert (folder / seed.MARKER_FILE).is_file()
        assert not (folder / seed.PROGRESS_FILE).exists()
    finally:
        close(services)
    again, _ = start(folder)
    try:
        assert statuses(again) == ["awaiting_review", "signed"]
    finally:
        close(again)


def test_a_stopped_seed_whose_batch_failed_starts_that_batch_again_by_itself(tmp_path, monkeypatch):
    from kyc_fakes import ScriptedReader

    folder = tmp_path / "state"
    failing = Services()
    service.use_models(ScriptedReader(fail_for=("CUST-003",)))
    try:
        with pytest.raises(SeedError, match="stopped before its review"):
            start(folder, failing)
    finally:
        service.use_models(None)
    close(failing)
    services, _ = start(folder)
    try:
        assert statuses(services) == ["awaiting_review", "failed", "signed"]
        assert (folder / seed.MARKER_FILE).is_file()
    finally:
        close(services)


def messages_of(folder: Path) -> str:
    refused = Services()
    try:
        with pytest.raises(SeedError) as caught:
            start(folder, refused)
    finally:
        close(refused)
    return str(caught.value)


def test_a_folder_the_seed_did_not_make_is_refused_without_advice_to_delete_it(tmp_path):
    folder = tmp_path / "state"
    own = KycRuns(models=ScriptedReader(), state_dir=folder)
    wait_until(own, own.start({"request": REQUEST_TEXT, "customer_ids": ["CUST-001"]}))
    own.close()
    words = messages_of(folder)
    assert "did not make" in words
    assert "delete" not in words.lower() and "remove" not in words.lower()
    assert "another APP_STATE_DIR" in words


def test_a_marker_made_from_other_recordings_is_refused_without_advice_to_delete_it(tmp_path):
    folder = tmp_path / "state"
    services, _ = start(folder)
    close(services)
    (folder / seed.MARKER_FILE).write_text(json.dumps({"seed": NAME, "digest": "sha256:x"}))
    words = messages_of(folder)
    assert "did not make" in words
    assert "delete" not in words.lower() and "remove" not in words.lower()
    assert "another APP_STATE_DIR" in words


def progress_file(folder: Path, **batches: str) -> None:
    """Write the progress file a stopped seed of this fixture and these recordings would leave."""
    folder.mkdir(parents=True, exist_ok=True)
    held = {"seed": seed.SEED_NAME, "digest": seed.seed_identity(), "batches": batches}
    (folder / seed.PROGRESS_FILE).write_text(json.dumps(held))


@pytest.mark.parametrize(
    "batches",
    [
        {"waiting": "no-such-thread"},
        {"waiting": "no-such-thread", "signed": "no-such-thread-either"},
        {"signed": "no-such-thread"},
    ],
)
def test_a_progress_file_naming_batches_the_folder_does_not_hold_starts_them_again(
    tmp_path, batches
):
    folder = tmp_path / "state"
    progress_file(folder, **batches)
    services, _ = start(folder)
    try:
        assert statuses(services) == ["awaiting_review", "signed"]
        assert (folder / seed.MARKER_FILE).is_file()
    finally:
        close(services)


def reviewer_client(app) -> TestClient:
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(app.state.cookie_name, SessionCodec(b"s").encode(seed.REVIEWER))
    return client


@pytest.mark.parametrize("customer", ["CUST-001", "CUST-025"])
def test_a_resumed_seed_never_overwrites_a_decision_already_recorded(
    tmp_path, monkeypatch, customer
):
    """CUST-001 was recorded by the stopped seed and then changed; CUST-025 was not reached."""
    folder = tmp_path / "state"
    stopped = Services()
    with monkeypatch.context() as stopping:
        stop_after(stopping, "_expect_redirect", 3)
        with pytest.raises(SeedError, match="stopped for the test"):
            start(folder, stopped)
    runs = stopped.runs()
    signed = next(t for t in runs.list_runs() if runs.status(t) == "awaiting_review")
    request = runs.review_request(signed)
    proposal = next(
        c.fact.id
        for s in request.statements
        for c in s.facts
        if c.fact.kind == "proposal" and c.fact.subject.anchor == f"row:{customer}"
    )
    app = create_app(
        AppConfig(secret=b"s", topic_folders=(), state_dir=None), topics=[build_plugin(stopped)]
    )
    own = reviewer_client(app).post(
        f"/kyc/runs/{signed}/decide",
        data={
            "brief_digest": request.brief_digest,
            "fact_id": proposal,
            "outcome": "amend",
            "amendment": "High risk, reject.",
            "reason": "Checked it again myself.",
        },
    )
    assert own.status_code == 303
    close(stopped)
    services, _ = start(folder)
    try:
        runs = services.runs()
        done = next(t for t in runs.list_runs() if runs.status(t) == "signed")
        held = [d for d in runs.result(done)["decisions"].values() if d["subject_id"] == proposal]
        assert [(d["outcome"], d["reason"]) for d in held] == [
            ("amend", "Checked it again myself.")
        ]
    finally:
        close(services)
