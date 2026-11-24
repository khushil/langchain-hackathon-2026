"""Tests of the run service the application calls: start, status, review, submit and errors."""

import threading
import time

import pytest
from context.errors import DocumentNotFoundError, FirmNotFoundError
from engine_fakes import ScriptedModels, respond
from langgraph.store.memory import InMemoryStore
from workflow.errors import InvalidRequestError
from workflow.runs import (
    BriefRuns,
    NotAwaitingReviewError,
    RunInProgressError,
    RunNotFoundError,
)

from fsi_common.ids import digest_bytes
from utils.db import DATA_DIR
from utils.state import ReviewMismatchError, ReviewRequest

REQUEST = {
    "document_id": "PS26-4",
    "firm_id": "FIRM-001",
    "request": "Summarise document PS26-4 for FIRM-001",
    "sections": ["7"],
}


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

    def slow(section):
        gate.wait(10)
        from engine_fakes import default_summary

        return default_summary(section)

    runs = BriefRuns(models=ScriptedModels(section=slow))
    thread_id = runs.start(REQUEST)
    assert runs.status(thread_id) == "running"
    with pytest.raises(NotAwaitingReviewError):
        runs.review_request(thread_id)
    gate.set()
    assert wait_until(runs, thread_id, {"awaiting_review"}) == "awaiting_review"
    assert isinstance(runs.review_request(thread_id), ReviewRequest)
    assert runs.error(thread_id) is None


def test_submit_a_signed_review_resumes_the_graph_to_its_end():
    runs = BriefRuns(models=ScriptedModels())
    thread_id = runs.start(REQUEST)
    wait_until(runs, thread_id, {"awaiting_review"})
    request = runs.review_request(thread_id)
    assert runs.submit(thread_id, respond(request)) == "signed"
    assert runs.status(thread_id) == "signed"
    assert runs.result(thread_id)["sign_off"]["outcome"] == "signed"
    with pytest.raises(NotAwaitingReviewError):
        runs.review_request(thread_id)
    with pytest.raises(NotAwaitingReviewError):
        runs.submit(thread_id, respond(request))


def test_submit_a_returned_review_ends_the_run_as_returned():
    runs = BriefRuns(models=ScriptedModels())
    thread_id = runs.start(REQUEST)
    wait_until(runs, thread_id, {"awaiting_review"})
    request = runs.review_request(thread_id)
    assert (
        runs.submit(thread_id, respond(request, outcome="returned", decide="reject")) == "returned"
    )
    assert runs.result(thread_id)["sign_off"]["reason"] == "Returned for a rewrite."


def test_submit_decisions_without_a_sign_off_leaves_the_run_awaiting_review():
    runs = BriefRuns(models=ScriptedModels())
    thread_id = runs.start(REQUEST)
    wait_until(runs, thread_id, {"awaiting_review"})
    partial = respond(runs.review_request(thread_id)).model_copy(update={"sign_off": None})
    assert runs.submit(thread_id, partial) == "awaiting_review"
    assert len(runs.result(thread_id)["decisions"]) == 5


def test_submit_a_response_for_another_brief_is_refused_and_the_run_still_waits():
    runs = BriefRuns(models=ScriptedModels())
    thread_id = runs.start(REQUEST)
    wait_until(runs, thread_id, {"awaiting_review"})
    request = runs.review_request(thread_id)
    other = request.model_copy(update={"brief_digest": "sha256:" + "0" * 64})
    with pytest.raises(ReviewMismatchError):
        runs.submit(thread_id, respond(other))
    assert runs.status(thread_id) == "awaiting_review"
    assert runs.submit(thread_id, respond(request)) == "signed"


def test_a_failing_model_call_gives_a_failed_run_with_the_failure_in_words():
    runs = BriefRuns(models=ScriptedModels(fail_sections=("7",)))
    thread_id = runs.start(REQUEST)
    assert wait_until(runs, thread_id, {"failed"}) == "failed"
    assert "the model call for section 7 failed" in runs.error(thread_id)
    with pytest.raises(NotAwaitingReviewError):
        runs.review_request(thread_id)


def test_start_refuses_a_second_run_while_one_is_running_and_allows_one_after():
    gate = threading.Event()

    def slow(section):
        gate.wait(10)
        from engine_fakes import default_summary

        return default_summary(section)

    runs = BriefRuns(models=ScriptedModels(section=slow))
    first = runs.start(REQUEST)
    with pytest.raises(RunInProgressError):
        runs.start(REQUEST)
    gate.set()
    wait_until(runs, first, {"awaiting_review"})
    second = runs.start(REQUEST)
    wait_until(runs, second, {"awaiting_review"})
    assert runs.list_runs() == [second, first]


def test_every_unknown_thread_id_raises_run_not_found():
    runs = BriefRuns(models=ScriptedModels())
    for call in (
        runs.status,
        runs.review_request,
        runs.result,
        runs.error,
        lambda t: runs.submit(t, None),
    ):
        with pytest.raises(RunNotFoundError, match="nope"):
            call("nope")


def test_start_refuses_a_request_for_an_unknown_document_firm_or_a_missing_field():
    runs = BriefRuns(models=ScriptedModels())
    with pytest.raises(DocumentNotFoundError):
        runs.start({**REQUEST, "document_id": "PS99-1"})
    with pytest.raises(FirmNotFoundError):
        runs.start({**REQUEST, "firm_id": "FIRM-404"})
    with pytest.raises(InvalidRequestError, match="firm_id"):
        runs.start({"document_id": "PS26-4", "request": "x"})
    assert runs.list_runs() == []


def test_a_rerun_through_the_service_carries_the_earlier_decisions():
    runs = BriefRuns(models=ScriptedModels())
    first = runs.start(REQUEST)
    wait_until(runs, first, {"awaiting_review"})
    runs.submit(first, respond(runs.review_request(first)))
    second = runs.start(REQUEST)
    wait_until(runs, second, {"awaiting_review"})
    request = runs.review_request(second)
    assert {c.carry.outcome for s in request.statements for c in s.facts} == {"carried"}


def test_the_run_configuration_names_the_run_and_carries_the_document_and_no_secret():
    runs = BriefRuns(models=ScriptedModels())
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
    document = DATA_DIR / "documents" / "PS26-4.md"
    assert start_config["run_name"] == "compliance-brief"
    assert start_config["max_concurrency"] == 4
    assert start_config["configurable"] == {"thread_id": thread_id}
    assert start_config["metadata"] == {
        "document_id": "PS26-4",
        "firm_id": "FIRM-001",
        "document_digest": digest_bytes(document.read_bytes()),
    }
    assert resume_config["metadata"] == {**start_config["metadata"], "reviewer": "Dana Whitfield"}
    assert resume_config["run_name"] == "compliance-brief"
    text = repr(seen).lower()
    assert "key" not in text and "token" not in text and "secret" not in text


def test_thread_ids_are_random_uuids_so_a_persisted_checkpointer_never_reopens_an_old_thread():
    import uuid

    first, second = BriefRuns(models=ScriptedModels()), BriefRuns(models=ScriptedModels())
    ids = [first.start(REQUEST), second.start(REQUEST)]
    assert len(set(ids)) == 2
    for thread_id in ids:
        assert uuid.UUID(thread_id).version == 4
    wait_until(first, ids[0], {"awaiting_review"})
    wait_until(second, ids[1], {"awaiting_review"})


def test_a_request_with_an_empty_section_list_is_refused_and_no_run_starts():
    runs = BriefRuns(models=ScriptedModels())
    with pytest.raises(InvalidRequestError, match="sections"):
        runs.start({**REQUEST, "sections": []})
    assert runs.list_runs() == []


def test_a_request_without_a_section_list_still_reads_every_section():
    runs = BriefRuns(models=ScriptedModels())
    request = {key: value for key, value in REQUEST.items() if key != "sections"}
    thread_id = runs.start(request)
    wait_until(runs, thread_id, {"awaiting_review"})
    assert len(runs.result(thread_id)["section_results"]) == 10


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
    runs = BriefRuns(models=ScriptedModels(), store=FlakyStore())
    thread_id = runs.start(REQUEST)
    wait_until(runs, thread_id, {"awaiting_review"})
    response = respond(runs.review_request(thread_id))
    assert runs.submit(thread_id, response) == "awaiting_review"
    assert "the store was unavailable" in runs.error(thread_id)
    assert runs.review_request(thread_id).brief_id == response.sign_off.brief_id
    assert runs.submit(thread_id, response) == "signed"
    assert runs.error(thread_id) is None


def test_a_failure_before_the_review_is_still_a_failed_run():
    runs = BriefRuns(models=ScriptedModels(fail_sections=("7",)))
    thread_id = runs.start(REQUEST)
    assert wait_until(runs, thread_id, {"failed"}) == "failed"
