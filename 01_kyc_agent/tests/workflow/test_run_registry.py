"""Tests of the files that keep the run service's state: the run list and the state folder."""

import sqlite3
from typing import get_args

import pytest

from utils.models import MAX_CONCURRENCY
from workflow.run_registry import (
    CHECKPOINT_FILE,
    RUNS_FILE,
    STORE_FILE,
    Registry,
    Run,
    RunStatus,
    StateFolderError,
    config_of,
    open_state_folder,
)

META = {"customers": 2, "applications_digest": "sha256:ab"}


def run_of(thread_id, **changes):
    return Run(
        thread_id=thread_id,
        config=config_of(thread_id, META),
        request={"request": "Review", "customer_ids": ["CUST-001"]},
        **changes,
    )


def test_the_configuration_names_the_thread_the_graph_and_the_concurrency_limit():
    config = config_of("t-1", META)
    assert config["configurable"] == {"thread_id": "t-1"}
    assert config["run_name"] == "kyc-onboarding"
    assert config["max_concurrency"] == MAX_CONCURRENCY
    assert {key: config["metadata"][key] for key in META} == META
    assert config["metadata"]["topic"] == "01-kyc-onboarding"
    assert config["metadata"]["thread_id"] == "t-1"
    assert "topic:01-kyc-onboarding" in config["tags"]


def test_a_configuration_rebuilt_from_what_the_registry_kept_is_the_same():
    config = config_of("t-1", META, run_id="r-1")
    assert config_of("t-1", config["metadata"], run_id="r-1") == config


def test_runs_are_read_back_oldest_first_with_their_request_configuration_and_status(tmp_path):
    registry = Registry(tmp_path / RUNS_FILE)
    first, second = run_of("t-1"), run_of("t-2")
    registry.add(first)
    registry.add(second)
    first.status, first.error = "failed", "No answer."
    registry.update(first)
    registry.close()
    loaded = Registry(tmp_path / RUNS_FILE).load()
    assert [r.thread_id for r in loaded] == ["t-1", "t-2"]
    assert (loaded[0].status, loaded[0].error) == ("failed", "No answer.")
    assert (loaded[1].status, loaded[1].error) == ("running", None)
    assert loaded[1].config == second.config and loaded[1].request == second.request


def test_a_second_run_with_the_same_thread_id_is_refused_naming_the_file(tmp_path):
    registry = Registry(tmp_path / RUNS_FILE)
    registry.add(run_of("t-1"))
    with pytest.raises(StateFolderError, match="runs.sqlite"):
        registry.add(run_of("t-1"))


def test_a_closed_registry_refuses_a_write_in_words(tmp_path):
    registry = Registry(tmp_path / RUNS_FILE)
    registry.close()
    with pytest.raises(StateFolderError, match="could not be kept"):
        registry.add(run_of("t-1"))


def test_a_folder_is_made_with_its_three_files_and_closed(tmp_path):
    folder = open_state_folder(tmp_path / "a" / "state")
    folder.registry.add(run_of("t-1"))
    folder.close()
    names = {p.name for p in (tmp_path / "a" / "state").iterdir()}
    assert {CHECKPOINT_FILE, STORE_FILE, RUNS_FILE} <= names
    with pytest.raises(sqlite3.ProgrammingError):
        folder.connections[0].execute("SELECT 1")


@pytest.mark.parametrize("name", [CHECKPOINT_FILE, STORE_FILE])
def test_a_checkpoint_or_store_file_that_is_not_a_database_is_refused_naming_it(tmp_path, name):
    (tmp_path / name).write_text("this is not a database, it is a sentence of text.")
    with pytest.raises(StateFolderError, match=name):
        open_state_folder(tmp_path)


def test_a_stored_status_that_is_not_one_of_the_run_statuses_is_refused_naming_the_run(tmp_path):
    registry = Registry(tmp_path / RUNS_FILE)
    registry.add(run_of("t-1"))
    registry.close()
    with sqlite3.connect(tmp_path / RUNS_FILE) as conn:
        conn.execute("UPDATE runs SET status = 'archived'")
    with pytest.raises(StateFolderError, match=r"t-1.*archived"):
        Registry(tmp_path / RUNS_FILE).load()


@pytest.mark.parametrize("status", get_args(RunStatus))
def test_every_run_status_is_read_back(tmp_path, status):
    registry = Registry(tmp_path / RUNS_FILE)
    registry.add(run_of("t-1", status=status))
    assert registry.load()[0].status == status


def test_a_second_server_on_a_folder_in_use_is_refused_in_words_until_the_first_is_closed(tmp_path):
    first = open_state_folder(tmp_path)
    with pytest.raises(StateFolderError, match="already in use.*another"):
        open_state_folder(tmp_path)
    first.close()
    open_state_folder(tmp_path).close()
