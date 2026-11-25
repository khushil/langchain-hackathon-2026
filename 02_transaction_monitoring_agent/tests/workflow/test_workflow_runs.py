"""The run service the application calls: start, status, review, submit and errors."""

import threading
import time
import uuid

import pytest
from engine_fakes import ScriptedModels, respond
from langgraph.store.memory import InMemoryStore

from context.errors import CustomerNotFoundError, EmptyStreamError
from fsi_common.ids import digest_bytes
from utils.db import DATA_DIR
from utils.review import ReviewMismatchError, ReviewRequest
from utils.state import OCT_19
from workflow.errors import InvalidRequestError
from workflow.runs import (
    MonitorRuns,
    NotAwaitingReviewError,
    RunInProgressError,
    RunNotFoundError,
)

REQUEST = {"user_id": "USR-001", "request": "Assess the transactions of USR-001", "end": OCT_19}


def wait_until(runs, thread_id, wanted, timeout=20.0):
    """Poll a run until its status is one of ``wanted``."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        status = runs.status(thread_id)
        if status in wanted:
            return status
        time.sleep(0.01)
    raise AssertionError(f"run {thread_id} is {runs.status(thread_id)}, not {wanted}")


def test_start_returns_at_once_and_the_run_reaches_the_review():
    gate = threading.Event()
    runs = MonitorRuns(models=ScriptedModels(hold=gate))
    thread_id = runs.start(REQUEST)
    assert runs.status(thread_id) == "running"
    with pytest.raises(NotAwaitingReviewError):
        runs.review_request(thread_id)
    gate.set()
    assert wait_until(runs, thread_id, {"awaiting_review"}) == "awaiting_review"
    assert isinstance(runs.review_request(thread_id), ReviewRequest)
    assert runs.error(thread_id) is None


def test_submit_a_signed_review_resumes_the_graph_to_its_end():
    runs = MonitorRuns(models=ScriptedModels())
    thread_id = runs.start(REQUEST)
    wait_until(runs, thread_id, {"awaiting_review"})
    request = runs.review_request(thread_id)
    assert runs.submit(thread_id, respond(request)) == "signed"
    assert runs.result(thread_id)["sign_off"]["outcome"] == "signed"
    with pytest.raises(NotAwaitingReviewError):
        runs.review_request(thread_id)
    with pytest.raises(NotAwaitingReviewError):
        runs.submit(thread_id, respond(request))


def test_submit_a_returned_review_ends_the_run_as_returned():
    runs = MonitorRuns(models=ScriptedModels())
    thread_id = runs.start(REQUEST)
    wait_until(runs, thread_id, {"awaiting_review"})
    request = runs.review_request(thread_id)
    assert runs.submit(thread_id, respond(request, outcome="returned", decide="reject")) == (
        "returned"
    )
    assert runs.result(thread_id)["sign_off"]["reason"] == "Returned for a rewrite."


def test_submit_decisions_without_a_sign_off_leaves_the_run_awaiting_review():
    runs = MonitorRuns(models=ScriptedModels())
    thread_id = runs.start(REQUEST)
    wait_until(runs, thread_id, {"awaiting_review"})
    partial = respond(runs.review_request(thread_id)).model_copy(update={"sign_off": None})
    assert runs.submit(thread_id, partial) == "awaiting_review"
    assert len(runs.result(thread_id)["decisions"]) == 6


def test_submit_a_response_for_another_brief_is_refused_and_the_run_still_waits():
    runs = MonitorRuns(models=ScriptedModels())
    thread_id = runs.start(REQUEST)
    wait_until(runs, thread_id, {"awaiting_review"})
    request = runs.review_request(thread_id)
    other = request.model_copy(update={"brief_digest": "sha256:" + "0" * 64})
    with pytest.raises(ReviewMismatchError):
        runs.submit(thread_id, respond(other))
    assert runs.status(thread_id) == "awaiting_review"
    assert runs.submit(thread_id, respond(request)) == "signed"


def test_a_refused_signature_leaves_the_run_waiting_and_a_return_or_a_full_decision_still_works():
    runs = MonitorRuns(models=ScriptedModels())
    thread_id = runs.start(REQUEST)
    wait_until(runs, thread_id, {"awaiting_review"})
    request = runs.review_request(thread_id)
    for refused in (respond(request, decide=None), respond(request, decide="reject")):
        with pytest.raises(ReviewMismatchError):
            runs.submit(thread_id, refused)
        assert runs.status(thread_id) == "awaiting_review"
    assert runs.submit(thread_id, respond(request, outcome="returned", decide="reject")) == (
        "returned"
    )


def test_a_failing_model_call_gives_a_failed_run_with_the_failure_in_words():
    runs = MonitorRuns(models=ScriptedModels(fail=("TX-1003",)))
    thread_id = runs.start(REQUEST)
    assert wait_until(runs, thread_id, {"failed"}) == "failed"
    assert "the model call for TX-1003 failed" in runs.error(thread_id)
    with pytest.raises(NotAwaitingReviewError):
        runs.review_request(thread_id)


def test_start_refuses_a_second_run_while_one_is_running_and_allows_one_after():
    gate = threading.Event()
    runs = MonitorRuns(models=ScriptedModels(hold=gate))
    first = runs.start(REQUEST)
    with pytest.raises(RunInProgressError):
        runs.start(REQUEST)
    gate.set()
    wait_until(runs, first, {"awaiting_review"})
    second = runs.start(REQUEST)
    wait_until(runs, second, {"awaiting_review"})
    assert runs.list_runs() == [second, first]


def test_every_unknown_thread_id_raises_run_not_found():
    runs = MonitorRuns(models=ScriptedModels())
    for call in (
        runs.status,
        runs.review_request,
        runs.result,
        runs.error,
        runs.root_run,
        lambda t: runs.submit(t, None),
    ):
        with pytest.raises(RunNotFoundError, match="nope"):
            call("nope")


def test_start_refuses_an_unknown_customer_an_empty_window_or_a_missing_field():
    runs = MonitorRuns(models=ScriptedModels())
    with pytest.raises(CustomerNotFoundError):
        runs.start({**REQUEST, "user_id": "USR-404"})
    with pytest.raises(EmptyStreamError):
        runs.start({**REQUEST, "user_id": "USR-002", "start": "2026-11-01", "end": None})
    with pytest.raises(InvalidRequestError, match="user_id"):
        runs.start({"request": "x"})
    assert runs.list_runs() == []


def test_a_rerun_through_the_service_carries_the_earlier_decisions():
    runs = MonitorRuns(models=ScriptedModels())
    first = runs.start(REQUEST)
    wait_until(runs, first, {"awaiting_review"})
    runs.submit(first, respond(runs.review_request(first)))
    second = runs.start(REQUEST)
    wait_until(runs, second, {"awaiting_review"})
    request = runs.review_request(second)
    assert {c.carry.outcome for c in request.assessments} == {"carried"}


def test_the_run_configuration_names_the_run_and_carries_the_customer_and_no_secret():
    runs = MonitorRuns(models=ScriptedModels())
    seen = []
    real = runs._graph

    class Recording:
        def invoke(self, payload, config):
            seen.append(config)
            return real.invoke(payload, config)

        def __getattr__(self, name):
            return getattr(real, name)

    runs._graph = Recording()
    thread_id = runs.start(REQUEST)
    wait_until(runs, thread_id, {"awaiting_review"})
    runs.submit(thread_id, respond(runs.review_request(thread_id)))
    start_config, resume_config = seen
    table = DATA_DIR / "transactions.jsonl"
    assert start_config["run_name"] == "transaction-monitoring"
    assert start_config["max_concurrency"] == 4
    assert start_config["configurable"] == {"thread_id": thread_id}
    assert start_config["metadata"] == {
        "user_id": "USR-001",
        "transactions_digest": digest_bytes(table.read_bytes()),
        "transactions": 6,
    }
    assert resume_config["metadata"] == {**start_config["metadata"], "reviewer": "Dana Whitfield"}
    text = repr(seen).lower()
    assert "key" not in text and "token" not in text and "secret" not in text


def test_thread_ids_are_random_uuids_so_a_persisted_checkpointer_never_reopens_an_old_thread():
    first, second = MonitorRuns(models=ScriptedModels()), MonitorRuns(models=ScriptedModels())
    ids = [first.start(REQUEST), second.start(REQUEST)]
    assert len(set(ids)) == 2
    for thread_id in ids:
        assert uuid.UUID(thread_id).version == 4
    wait_until(first, ids[0], {"awaiting_review"})
    wait_until(second, ids[1], {"awaiting_review"})


def test_thread_ids_sort_in_the_order_the_runs_were_made_and_never_repeat():
    from workflow.runs import new_thread_id

    ids = [new_thread_id() for _ in range(2000)]
    assert ids == sorted(ids)
    assert len(set(ids)) == 2000
    assert {uuid.UUID(i).version for i in ids} == {4}
    assert {uuid.UUID(i).variant for i in ids} == {uuid.RFC_4122}


class FlakyStore(InMemoryStore):
    """A store whose first write fails, as a store can when the disk or the network does."""

    def __init__(self) -> None:
        super().__init__()
        self.failures = 1

    def put(self, namespace, key, value, *args, **kwargs):
        if self.failures:
            self.failures -= 1
            raise RuntimeError("the store was unavailable")
        return super().put(namespace, key, value, *args, **kwargs)


def test_a_resume_that_fails_inside_the_graph_returns_the_run_to_the_review_and_records_why():
    runs = MonitorRuns(models=ScriptedModels(), store=FlakyStore())
    thread_id = runs.start(REQUEST)
    wait_until(runs, thread_id, {"awaiting_review"})
    response = respond(runs.review_request(thread_id))
    assert runs.submit(thread_id, response) == "awaiting_review"
    assert "the store was unavailable" in runs.error(thread_id)
    assert runs.review_request(thread_id).brief_id == response.sign_off.brief_id
    assert runs.submit(thread_id, response) == "signed"
    assert runs.error(thread_id) is None


def test_result_holds_the_request_before_the_graph_writes_its_first_checkpoint(monkeypatch):
    held = threading.Event()
    monkeypatch.setattr(MonitorRuns, "_execute", lambda self, run, graph_input: held.wait(10))
    runs = MonitorRuns(models=ScriptedModels())
    thread_id = runs.start(REQUEST)
    try:
        state = runs.result(thread_id)
        assert state["request"]["user_id"] == "USR-001"
        assert state["request"]["end"] == OCT_19
    finally:
        held.set()
