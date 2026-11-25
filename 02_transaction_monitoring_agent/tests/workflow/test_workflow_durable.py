"""The run service kept in files: a new service on the same folder finds the same runs."""

import shutil
import sqlite3
import threading

import pytest
from engine_fakes import ScriptedModels, respond
from test_workflow_runs import REQUEST, wait_until

from workflow.run_registry import LOCK_FILE
from workflow.runs import MonitorRuns, StateFolderError


@pytest.fixture()
def folder(tmp_path):
    return tmp_path / "state"


def open_runs(folder, **options):
    return MonitorRuns(models=options.pop("models", None) or ScriptedModels(), state_dir=folder)


def signed_run(runs):
    thread_id = runs.start(REQUEST)
    wait_until(runs, thread_id, {"awaiting_review"})
    assert runs.submit(thread_id, respond(runs.review_request(thread_id))) == "signed"
    return thread_id


def test_a_new_service_on_the_same_folder_finds_the_run_its_status_decisions_and_sign_off(folder):
    first = open_runs(folder)
    thread_id = signed_run(first)
    before = first.result(thread_id)
    first.close()
    second = open_runs(folder)
    assert second.list_runs() == [thread_id]
    assert second.status(thread_id) == "signed"
    after = second.result(thread_id)
    assert after["request"] == before["request"] == {**REQUEST}
    assert after["sign_off"] == before["sign_off"]
    assert after["decisions"] == before["decisions"] and len(after["decisions"]) == 6
    assert second.error(thread_id) is None
    second.close()


def test_a_later_run_on_the_same_customer_carries_the_decisions_after_a_restart(folder):
    first = open_runs(folder)
    signed_run(first)
    first.close()
    second = open_runs(folder)
    thread_id = second.start(REQUEST)
    wait_until(second, thread_id, {"awaiting_review"})
    request = second.review_request(thread_id)
    assert {c.carry.outcome for c in request.assessments} == {"carried"}
    assert len(request.history) == 6
    second.close()


def test_a_run_waiting_for_a_reviewer_is_still_waiting_after_a_restart_and_can_be_signed(folder):
    first = open_runs(folder)
    thread_id = first.start(REQUEST)
    wait_until(first, thread_id, {"awaiting_review"})
    shown = first.review_request(thread_id)
    first.close()
    second = open_runs(folder)
    assert second.status(thread_id) == "awaiting_review"
    assert second.review_request(thread_id) == shown
    assert second.submit(thread_id, respond(shown)) == "signed"
    second.close()


def test_runs_are_listed_newest_first_after_a_restart(folder):
    first = open_runs(folder)
    older = signed_run(first)
    newer = first.start(REQUEST)
    wait_until(first, newer, {"awaiting_review"})
    first.close()
    second = open_runs(folder)
    assert second.list_runs() == [newer, older]
    second.close()


def test_a_failed_run_keeps_its_failure_in_words_after_a_restart(folder):
    first = open_runs(folder, models=ScriptedModels(fail=("TX-1003",)))
    thread_id = first.start(REQUEST)
    wait_until(first, thread_id, {"failed"})
    words = first.error(thread_id)
    first.close()
    second = open_runs(folder)
    assert second.status(thread_id) == "failed"
    assert second.error(thread_id) == words and words
    second.close()


def set_status(folder, thread_id, status):
    with sqlite3.connect(folder / "runs.sqlite") as conn:
        conn.execute("UPDATE runs SET status = ? WHERE thread_id = ?", (status, thread_id))


def test_a_run_a_stopped_server_left_running_at_its_review_is_waiting_again(folder):
    first = open_runs(folder)
    thread_id = first.start(REQUEST)
    wait_until(first, thread_id, {"awaiting_review"})
    first.close()
    set_status(folder, thread_id, "running")
    second = open_runs(folder)
    assert second.status(thread_id) == "awaiting_review"
    second.close()


def test_a_run_a_stopped_server_left_running_after_its_sign_off_is_signed_again(folder):
    first = open_runs(folder)
    thread_id = signed_run(first)
    first.close()
    set_status(folder, thread_id, "running")
    second = open_runs(folder)
    assert second.status(thread_id) == "signed"
    second.close()


def test_a_run_a_stopped_server_left_running_before_its_review_is_failed_in_words(folder):
    gate = threading.Event()
    first = open_runs(folder, models=ScriptedModels(hold=gate, fail=("TX-1001",)))
    thread_id = first.start(REQUEST)
    set_status(folder, thread_id, "running")
    copy = folder.parent / "copy"  # the first service still holds the folder, as a live server does
    shutil.copytree(folder, copy, ignore=shutil.ignore_patterns(LOCK_FILE))
    try:
        second = open_runs(copy)
        assert second.status(thread_id) == "failed"
        assert "stopped before the review was reached" in second.error(thread_id)
        second.close()
    finally:
        gate.set()
        wait_until(first, thread_id, {"failed"})
        first.close()


def test_without_a_folder_nothing_is_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runs = MonitorRuns(models=ScriptedModels())
    signed_run(runs)
    assert list(tmp_path.iterdir()) == []


def test_a_folder_and_a_checkpointer_together_are_refused_in_words(folder):
    from langgraph.checkpoint.memory import InMemorySaver

    with pytest.raises(StateFolderError, match="state folder.*checkpointer"):
        MonitorRuns(models=ScriptedModels(), state_dir=folder, checkpointer=InMemorySaver())


def test_a_folder_that_cannot_be_made_is_refused_naming_it(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    with pytest.raises(StateFolderError, match="file"):
        MonitorRuns(models=ScriptedModels(), state_dir=blocker / "state")


def test_a_run_file_that_is_not_a_database_is_refused_naming_the_file(folder):
    folder.mkdir()
    (folder / "runs.sqlite").write_text("this is not a database, it is a sentence of text.")
    with pytest.raises(StateFolderError, match="runs.sqlite"):
        open_runs(folder)


def test_a_stored_request_that_cannot_be_read_is_refused_naming_the_run(folder):
    first = open_runs(folder)
    thread_id = signed_run(first)
    first.close()
    with sqlite3.connect(folder / "runs.sqlite") as conn:
        conn.execute("UPDATE runs SET request = 'not json' WHERE thread_id = ?", (thread_id,))
    with pytest.raises(StateFolderError, match=thread_id):
        open_runs(folder)


def test_threads_reading_a_run_while_it_proceeds_meet_no_error_and_see_each_status(folder):
    gate = threading.Event()
    runs = open_runs(folder, models=ScriptedModels(hold=gate))
    thread_id = runs.start(REQUEST)
    seen, errors = set(), []

    def watch():
        try:
            for _ in range(60):
                seen.add(runs.status(thread_id))
                runs.list_runs()
                runs.result(thread_id)
        except Exception as exc:  # collected so the test can name it
            errors.append(exc)

    watchers = [threading.Thread(target=watch) for _ in range(6)]
    for watcher in watchers:
        watcher.start()
    gate.set()
    for watcher in watchers:
        watcher.join(30)
    wait_until(runs, thread_id, {"awaiting_review"})
    assert errors == [] and seen <= {"running", "awaiting_review"}
    runs.close()
