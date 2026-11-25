"""Tests of the id a brief's root run is traced under, which the run service stores."""

import datetime
import sqlite3
import time
import uuid
from contextvars import ContextVar
from types import SimpleNamespace

import pytest
from engine_fakes import respond
from kyc_fakes import ScriptedReader
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.context import register_configure_hook
from langsmith.utils import LangSmithConnectionError, LangSmithNotFoundError

from workflow.run_registry import (
    RUNS_FILE,
    ProjectLookup,
    Registry,
    Run,
    config_of,
)
from workflow.runs import KycRuns, RunNotFoundError

REQUEST = {"request": "Review the proposed decisions", "customer_ids": ["CUST-001"]}
META = {"customers": 1, "applications_digest": "sha256:ab"}


class RootRuns(BaseCallbackHandler):
    """Keeps the id of every run that has no parent, while a test has switched it on."""

    def __init__(self):
        self.seen: list[str] | None = None

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        if self.seen is not None and parent_run_id is None:
            self.seen.append(str(run_id))


ROOTS = RootRuns()
register_configure_hook(ContextVar("root_runs", default=ROOTS), inheritable=True)


@pytest.fixture()
def root_runs():
    ROOTS.seen = []
    yield ROOTS.seen
    ROOTS.seen = None


def wait_for(runs, thread_id, wanted="awaiting_review"):
    end = time.monotonic() + 20
    while runs.status(thread_id) != wanted:
        assert time.monotonic() < end, f"run is {runs.status(thread_id)}"
        time.sleep(0.01)


def run_with(run_id=None):
    return Run(thread_id="t-1", config=config_of("t-1", META, run_id=run_id))


def test_a_configuration_holds_a_run_id_only_when_it_is_given_one():
    assert config_of("t-1", META, run_id="r-1")["run_id"] == "r-1"
    assert "run_id" not in config_of("t-1", META)


def test_a_run_id_is_kept_in_the_runs_file_and_read_back(tmp_path):
    registry = Registry(tmp_path / RUNS_FILE)
    registry.add(run_with("11111111-1111-4111-8111-111111111111"))
    registry.close()
    (loaded,) = Registry(tmp_path / RUNS_FILE).load()
    assert loaded.run_id == "11111111-1111-4111-8111-111111111111"
    assert loaded.config["run_id"] == loaded.run_id


def test_a_runs_file_made_before_run_ids_is_opened_and_its_runs_have_none(tmp_path):
    path = tmp_path / RUNS_FILE
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE runs (seq INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL UNIQUE, "
        "request TEXT NOT NULL, metadata TEXT NOT NULL, status TEXT NOT NULL, error TEXT)"
    )
    conn.execute(
        "INSERT INTO runs (thread_id, request, metadata, status) VALUES (?, ?, ?, ?)",
        ("old", '{"document_id": "PS26-4"}', '{"document_id": "PS26-4"}', "signed"),
    )
    conn.commit()
    conn.close()
    registry = Registry(path)
    (old,) = registry.load()
    assert old.run_id is None and "run_id" not in old.config
    registry.add(run_with("22222222-2222-4222-8222-222222222222"))
    assert [r.run_id for r in registry.load()] == [None, "22222222-2222-4222-8222-222222222222"]


def test_a_run_started_has_a_run_id_the_service_gives_and_each_run_has_its_own():
    runs = KycRuns(models=ScriptedReader())
    first = runs.start(REQUEST)
    wait_for(runs, first)
    second = runs.start(REQUEST)
    wait_for(runs, second)
    ids = [runs.root_run_id(first), runs.root_run_id(second)]
    assert all(uuid.UUID(i).version == 4 for i in ids)
    assert ids[0] != ids[1]


def test_the_id_the_service_stores_is_the_one_the_run_was_traced_under(root_runs):
    runs = KycRuns(models=ScriptedReader())
    thread_id = runs.start(REQUEST)
    wait_for(runs, thread_id)
    assert root_runs == [runs.root_run_id(thread_id)]


def test_the_review_resumes_under_a_new_run_so_the_briefs_run_keeps_its_id(root_runs):
    runs = KycRuns(models=ScriptedReader())
    thread_id = runs.start(REQUEST)
    wait_for(runs, thread_id)
    stored = runs.root_run_id(thread_id)
    runs.submit(thread_id, respond(runs.review_request(thread_id)))
    assert root_runs[0] == stored
    assert len(root_runs) == 2 and root_runs[1] != stored
    assert runs.root_run_id(thread_id) == stored


def test_a_service_opened_on_the_same_folder_later_gives_the_same_id(tmp_path):
    runs = KycRuns(models=ScriptedReader(), state_dir=tmp_path)
    thread_id = runs.start(REQUEST)
    wait_for(runs, thread_id)
    stored = runs.root_run_id(thread_id)
    runs.close()
    again = KycRuns(models=ScriptedReader(), state_dir=tmp_path)
    assert again.root_run_id(thread_id) == stored
    again.close()


def test_a_thread_the_service_does_not_know_has_no_run_id():
    with pytest.raises(RunNotFoundError, match="no-such"):
        KycRuns(models=ScriptedReader()).root_run_id("no-such")


PROJECT = "7b6a5f4e-0000-4000-8000-0000000000aa"
LIVE_ENV = {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "a-key-from-the-test"}


def test_a_run_keeps_the_project_and_the_start_time_the_service_recorded_beside_its_run_id():
    before = datetime.datetime.now(datetime.UTC)
    runs = KycRuns(models=ScriptedReader(), project_id=lambda: PROJECT)
    thread_id = runs.start(REQUEST)
    wait_for(runs, thread_id)
    root = runs.root_run(thread_id)
    assert root.run_id == runs.root_run_id(thread_id) and root.project_id == PROJECT
    started = datetime.datetime.fromisoformat(root.started_at)
    assert started.tzinfo is not None
    assert before <= started <= datetime.datetime.now(datetime.UTC)


def test_the_project_and_start_time_survive_a_restart_of_the_service(tmp_path):
    runs = KycRuns(models=ScriptedReader(), state_dir=tmp_path, project_id=lambda: PROJECT)
    thread_id = runs.start(REQUEST)
    wait_for(runs, thread_id)
    kept = runs.root_run(thread_id)
    runs.close()
    again = KycRuns(models=ScriptedReader(), state_dir=tmp_path)
    assert again.root_run(thread_id) == kept
    again.close()


def test_a_runs_file_made_before_the_project_and_start_time_is_opened(tmp_path):
    path = tmp_path / RUNS_FILE
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE runs (seq INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL UNIQUE, "
        "request TEXT NOT NULL, metadata TEXT NOT NULL, status TEXT NOT NULL, error TEXT, "
        "run_id TEXT)"
    )
    conn.execute(
        "INSERT INTO runs (thread_id, request, metadata, status, run_id) VALUES (?, ?, ?, ?, ?)",
        ("old", '{"document_id": "PS26-4"}', '{"document_id": "PS26-4"}', "signed", "r-old"),
    )
    conn.commit()
    conn.close()
    registry = Registry(path)
    (old,) = registry.load()
    assert (old.run_id, old.project_id, old.started_at) == ("r-old", None, None)


def test_a_project_that_cannot_be_found_at_the_start_is_looked_for_again_when_the_run_has_traced():
    answers = iter([None, PROJECT])
    runs = KycRuns(models=ScriptedReader(), project_id=lambda: next(answers))
    thread_id = runs.start(REQUEST)
    wait_for(runs, thread_id)
    assert runs.root_run(thread_id).project_id == PROJECT


def test_a_lookup_that_fails_does_not_stop_the_run_and_leaves_the_project_unknown():
    def failing():
        raise LangSmithConnectionError("LangSmith could not be reached")

    runs = KycRuns(models=ScriptedReader(), project_id=failing)
    thread_id = runs.start(REQUEST)
    wait_for(runs, thread_id)
    assert runs.root_run(thread_id).project_id is None
    assert runs.error(thread_id) is None


class FakeProjects:
    def __init__(self, *, known=True):
        self.asked, self.known = [], known

    def read_project(self, *, project_name, **kwargs):
        self.asked.append(project_name)
        if not self.known:
            raise LangSmithNotFoundError(f"Project {project_name} not found")
        return SimpleNamespace(id=PROJECT, name=project_name)


def lookup(client, env):
    return ProjectLookup(env=env, make_client=lambda env: client)


def test_with_tracing_off_no_client_is_made_and_no_project_is_looked_for():
    def refuse(env):
        raise AssertionError("a client was made with tracing off")

    assert ProjectLookup(env={"LANGSMITH_TRACING": "false"}, make_client=refuse)() is None


def test_the_project_is_looked_up_by_the_name_in_the_environment_once_per_process():
    client = FakeProjects()
    env = {**LIVE_ENV, "LANGSMITH_PROJECT": "compliance-brief"}
    find = lookup(client, env)
    assert find() == PROJECT and find() == PROJECT
    assert client.asked == ["compliance-brief"]


def test_a_project_that_does_not_exist_yet_is_not_remembered_as_missing():
    client = FakeProjects(known=False)
    find = lookup(client, {**LIVE_ENV, "LANGSMITH_PROJECT": "compliance-brief"})
    assert find() is None
    client.known = True
    assert find() == PROJECT
    assert client.asked == ["compliance-brief", "compliance-brief"]


def test_tracing_on_without_a_key_leaves_the_project_unknown_in_words():
    find = ProjectLookup(env={"LANGSMITH_TRACING": "true"}, make_client=None)
    assert find() is None
