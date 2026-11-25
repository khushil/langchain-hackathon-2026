"""Tests of what the reviewer's application sends to LangSmith when a brief is signed or returned.

The client is a fake that records every call. No test reaches the network or writes to LangSmith.
"""

from __future__ import annotations

import datetime
import threading
import time
from types import SimpleNamespace

import pytest
from langsmith.utils import LangSmithConnectionError
from review_fakes import FakeRuns, examples_review
from review_fixtures import DANA, make_client, make_client_for
from review_helpers import RUN, settle_everything

from review_app import feedback
from review_app.feedback import FAILED_WORDS, FEEDBACK_KEY, QUEUE_NAME

RUN_ID = "5d1c6f0a-6a1f-4e77-9a53-0d5b2f0d9c11"
PROJECT_ID = "9a8b7c6d-0000-4000-8000-00000000abcd"
STARTED_AT = "2026-11-25T09:00:00+00:00"
STARTED = datetime.datetime.fromisoformat(STARTED_AT)
QUEUE_ID = "3f2e1d0c-0000-4000-8000-00000000beef"


class FakeLangSmith:
    """The parts of the LangSmith client the application uses, recording each call."""

    def __init__(self, *, queues=(), fail_feedback_at=None, fail=()):
        self.queues = list(queues)
        self.feedback: list[dict] = []
        self.created: list[dict] = []
        self.added: list[dict] = []
        self.attempts: list[dict] = []
        self.hold = (
            None  # an event the feedback call waits for, to stand in for a stalled LangSmith
        )
        self.fail_feedback_at, self.fail = fail_feedback_at, set(fail)

    def _maybe_fail(self, name):
        if name in self.fail:
            raise LangSmithConnectionError(f"{name} could not connect")

    def create_feedback(self, run_id=None, key="unnamed", **kwargs):
        self.attempts.append(kwargs)
        if self.hold is not None:
            self.hold.wait(10)
        self._maybe_fail("create_feedback")
        if self.fail_feedback_at == len(self.attempts):
            self.fail_feedback_at = None
            raise LangSmithConnectionError("the feedback could not be sent")
        self.feedback.append({"run_id": run_id, "key": key, **kwargs})

    def list_annotation_queues(self, *, name=None, **kwargs):
        self._maybe_fail("list_annotation_queues")
        return iter([q for q in self.queues if name is None or name in q.name])

    def create_annotation_queue(self, *, name, description=None, **kwargs):
        self._maybe_fail("create_annotation_queue")
        queue = SimpleNamespace(id=QUEUE_ID, name=name)
        self.created.append({"name": name, "description": description})
        self.queues.append(queue)
        return queue

    def add_runs_to_annotation_queue(self, queue_id, *, runs=None, run_ids=None):
        self._maybe_fail("add_runs_to_annotation_queue")
        self.added.append({"queue_id": queue_id, "runs": runs, "run_ids": run_ids})


def signed_run(run_id=RUN_ID, *, project_id=PROJECT_ID, started_at=STARTED_AT):
    """A run waiting for its reviewer on the contract's example brief, with where it was traced."""
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=examples_review())
    runs.roots["run-1"] = SimpleNamespace(
        run_id=run_id, project_id=project_id, started_at=started_at
    )
    return runs


def sign(client, runs, *, outcome="signed", reason=None):
    review = settle_everything(client, runs)
    body = {"brief_digest": review.request.brief_digest, "outcome": outcome}
    if reason:
        body["reason"] = reason
    return client.post(f"{RUN}/sign", data=body)


def test_each_decision_goes_to_langsmith_as_feedback_on_the_briefs_run_with_the_reviewers_words():
    runs, ls = signed_run(), FakeLangSmith()
    sign(make_client(runs, feedback=lambda: ls, notes={}), runs)
    [(_, response)] = runs.submitted
    decisions = [f for f in ls.feedback if f["value"] in {"accept", "amend", "reject", "answer"}]
    assert len(decisions) == len(response.decisions) == 2
    for sent, decision in zip(decisions, response.decisions, strict=True):
        assert sent["run_id"] == RUN_ID and sent["key"] == FEEDBACK_KEY
        assert sent["value"] == decision.outcome
        assert sent["comment"] == decision.reason
        assert sent["source_info"] == {"reviewer": "Dana Whitfield", "role": "Head of Compliance"}
        assert sent["extra"] == {"subject_id": decision.subject_id}
        assert "trace_id" not in sent


def test_the_sign_off_is_sent_too_as_one_more_decision_on_the_same_run():
    runs, ls = signed_run(), FakeLangSmith()
    sign(make_client(runs, feedback=lambda: ls, notes={}), runs)
    *_, last = ls.feedback
    assert last["run_id"] == RUN_ID and last["key"] == FEEDBACK_KEY
    assert last["value"] == "signed" and last["comment"] is None
    assert len(ls.feedback) == len(runs.submitted[0][1].decisions) + 1


def test_a_returned_brief_sends_the_reason_the_reviewer_gave():
    runs, ls = signed_run(), FakeLangSmith()
    sign(
        make_client(runs, feedback=lambda: ls, notes={}),
        runs,
        outcome="returned",
        reason="The deadlines need another reading.",
    )
    *_, last = ls.feedback
    assert (last["value"], last["comment"]) == ("returned", "The deadlines need another reading.")
    assert last["source_info"]["reviewer"] == DANA.name


def test_the_run_goes_into_the_named_queue_which_is_made_once_when_it_is_absent():
    ls = FakeLangSmith()
    other_run_id = "6e2d6f0a-6a1f-4e77-9a53-0d5b2f0d9c22"
    for run_id in (RUN_ID, other_run_id):
        runs = signed_run(run_id)
        sign(make_client(runs, feedback=lambda: ls, notes={}), runs)
    assert [q["name"] for q in ls.created] == [QUEUE_NAME] == ["compliance-brief-reviews"]
    assert [a["queue_id"] for a in ls.added] == [QUEUE_ID, QUEUE_ID]
    assert [a["runs"][0]["run_id"] for a in ls.added] == [RUN_ID, other_run_id]
    assert ls.added[0]["runs"] == [
        {"run_id": RUN_ID, "session_id": PROJECT_ID, "start_time": STARTED}
    ]
    assert ls.added[0]["run_ids"] is None


def test_a_queue_that_exists_is_used_and_not_made_again():
    ls = FakeLangSmith(queues=[SimpleNamespace(id=QUEUE_ID, name=QUEUE_NAME)])
    runs = signed_run()
    sign(make_client(runs, feedback=lambda: ls, notes={}), runs)
    assert ls.created == [] and ls.added[0]["queue_id"] == QUEUE_ID


def test_a_queue_with_a_longer_name_is_not_taken_for_the_named_one():
    ls = FakeLangSmith(queues=[SimpleNamespace(id="other", name=QUEUE_NAME + "-old")])
    runs = signed_run()
    sign(make_client(runs, feedback=lambda: ls, notes={}), runs)
    assert [q["name"] for q in ls.created] == [QUEUE_NAME]
    assert ls.added[0]["queue_id"] == QUEUE_ID


def test_with_tracing_off_nothing_is_sent_and_nothing_fails(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGSMITH_API_KEY", "a-key-from-the-test")
    monkeypatch.setattr(
        feedback, "new_client", lambda env: pytest.fail("a client was made with tracing off")
    )
    runs = signed_run()
    notes = {}
    done = sign(make_client(runs, notes=notes), runs)
    assert done.status_code == 303 and runs.submitted and notes == {}


def test_a_send_that_fails_leaves_the_decision_kept_and_says_so_once_on_the_signed_page():
    ls = FakeLangSmith(fail=["create_feedback"])
    runs = signed_run()
    client = make_client(runs, feedback=lambda: ls, notes={})
    done = sign(client, runs)
    assert done.status_code == 303 and done.headers["location"] == f"{RUN}/signed"
    assert runs.submitted[0][1].sign_off.outcome == "signed"
    first = client.get(f"{RUN}/signed")
    assert first.text.count(FAILED_WORDS) == 1
    assert "Dana Whitfield, Head of Compliance, signed the brief" in first.text
    assert first.text.count("<tr>") == 3
    assert client.get(f"{RUN}/signed").text.count(FAILED_WORDS) == 1


def test_after_the_first_feedback_that_fails_nothing_more_is_sent_and_the_queue_is_left():
    ls = FakeLangSmith(fail_feedback_at=1)
    runs = signed_run()
    client = make_client(runs, feedback=lambda: ls, notes={})
    sign(client, runs)
    assert len(ls.attempts) == 1 and ls.feedback == [] and ls.added == []
    assert client.get(f"{RUN}/signed").text.count(FAILED_WORDS) == 1


def test_a_later_feedback_that_fails_keeps_what_was_sent_and_stops_there():
    ls = FakeLangSmith(fail_feedback_at=2)
    runs = signed_run()
    client = make_client(runs, feedback=lambda: ls, notes={})
    sign(client, runs)
    assert len(ls.attempts) == 2 and len(ls.feedback) == 1 and ls.added == []
    assert client.get(f"{RUN}/signed").text.count(FAILED_WORDS) == 1


def test_every_feedback_is_asked_for_at_most_two_attempts():
    ls = FakeLangSmith()
    runs = signed_run()
    sign(make_client(runs, feedback=lambda: ls, notes={}), runs)
    assert ls.attempts and all(a["stop_after_attempt"] == 2 for a in ls.attempts)


def test_a_queue_that_cannot_be_reached_is_said_in_the_same_sentence():
    ls = FakeLangSmith(fail=["add_runs_to_annotation_queue"])
    runs = signed_run()
    client = make_client(runs, feedback=lambda: ls, notes={})
    sign(client, runs)
    assert len(ls.feedback) == 3
    assert client.get(f"{RUN}/signed").text.count(FAILED_WORDS) == 1


def test_a_queue_that_cannot_be_listed_leaves_the_feedback_sent_and_says_so():
    ls = FakeLangSmith(fail=["list_annotation_queues"])
    runs = signed_run()
    client = make_client(runs, feedback=lambda: ls, notes={})
    sign(client, runs)
    assert len(ls.feedback) == 3 and ls.added == []
    assert client.get(f"{RUN}/signed").text.count(FAILED_WORDS) == 1


def test_a_run_with_no_run_id_sends_nothing_and_says_so():
    ls = FakeLangSmith()
    runs = signed_run()
    del runs.roots["run-1"]
    client = make_client(runs, feedback=lambda: ls, notes={})
    sign(client, runs)
    assert ls.feedback == [] and ls.added == []
    assert client.get(f"{RUN}/signed").text.count(FAILED_WORDS) == 1


def test_tracing_on_without_a_key_says_so_and_still_keeps_the_decision(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_KEY", raising=False)
    runs = signed_run()
    client = make_client(runs, notes={})
    sign(client, runs)
    assert runs.submitted
    assert client.get(f"{RUN}/signed").text.count(FAILED_WORDS) == 1


def test_the_note_is_kept_for_the_run_that_failed(monkeypatch):
    runs = signed_run()
    notes = {}
    client = make_client(
        runs, feedback=lambda: FakeLangSmith(fail=["create_feedback"]), notes=notes
    )
    sign(client, runs)
    assert notes == {"run-1": FAILED_WORDS}


def test_the_sentence_is_in_plain_words_with_no_stack_trace_and_no_code():
    assert FAILED_WORDS == (
        "Your decisions are kept here, but some may not have reached the LangSmith review queue; "
        "tell the person who runs this server."
    )
    assert FAILED_WORDS.count(".") == 1
    assert "could not be sent" not in FAILED_WORDS and "were not sent" not in FAILED_WORDS


def test_the_current_forms_are_called_with_the_project_id_and_the_start_time():
    ls = FakeLangSmith()
    runs = signed_run()
    sign(make_client(runs, feedback=lambda: ls, notes={}), runs)
    assert ls.feedback
    for sent in ls.feedback:
        assert sent["run_id"] == RUN_ID
        assert sent["session_id"] == PROJECT_ID and sent["start_time"] == STARTED
    [added] = ls.added
    assert added["run_ids"] is None
    assert added["runs"] == [{"run_id": RUN_ID, "session_id": PROJECT_ID, "start_time": STARTED}]


@pytest.mark.parametrize("missing", ["project_id", "started_at"])
def test_a_run_whose_project_or_start_time_is_not_known_sends_nothing_and_says_so(missing):
    ls = FakeLangSmith()
    runs = signed_run(**{missing: None})
    client = make_client(runs, feedback=lambda: ls, notes={})
    sign(client, runs)
    assert ls.feedback == [] and ls.added == []
    assert client.get(f"{RUN}/signed").text.count(FAILED_WORDS) == 1


def test_a_stalled_langsmith_holds_the_sign_request_for_no_more_than_the_budget(monkeypatch):
    monkeypatch.setattr(feedback, "SEND_BUDGET_SECONDS", 0.3)
    ls = FakeLangSmith()
    ls.hold = threading.Event()
    runs = signed_run()
    client = make_client(runs, feedback=lambda: ls, notes={})
    began = time.monotonic()
    done = sign(client, runs)
    took = time.monotonic() - began
    ls.hold.set()
    assert done.status_code == 303 and runs.submitted
    assert took < 2.0
    assert client.get(f"{RUN}/signed").text.count(FAILED_WORDS) == 1


def sixty_decisions():
    """A response with as many decisions as a long brief holds, and a sign-off."""
    person = SimpleNamespace(name="Dana Whitfield", role="Head of Compliance")
    decisions = [
        SimpleNamespace(
            outcome="accept", reason="Checked.", reviewer=person, subject_id=f"fact:{n}"
        )
        for n in range(60)
    ]
    sign_off = SimpleNamespace(outcome="signed", reason=None, reviewer=person, brief_id="brief:1")
    return SimpleNamespace(decisions=decisions, sign_off=sign_off)


class Failure:
    """What a patched session does to every request: answer 500, or fail to connect."""

    def __init__(self, kind):
        self.kind, self.requests = kind, []

    def __call__(self, method, url, **kwargs):
        import requests

        self.requests.append((method, url.rsplit("/", 1)[-1], kwargs.get("timeout")))
        if self.kind == "connection":
            raise requests.exceptions.ConnectionError("no route")
        response = requests.Response()
        response.status_code = 500
        response.url = url
        response._content = b'{"detail": "server error"}'
        return response


@pytest.mark.parametrize("kind", ["server error", "connection"])
def test_with_every_call_failing_a_real_client_makes_two_attempts_and_waits_under_ten_seconds(
    kind,
):
    from langsmith import client as langsmith_client

    sleeps = []
    original = langsmith_client.time.sleep
    langsmith_client.time.sleep = sleeps.append
    try:
        client = feedback.new_client({"LANGSMITH_API_KEY": "a-key-from-the-test"})
        client.session.request = Failure(kind)
        root = SimpleNamespace(run_id=RUN_ID, project_id=PROJECT_ID, started_at=STARTED_AT)
        words = feedback.report_to_queue(lambda: client, lambda: root, sixty_decisions())
    finally:
        langsmith_client.time.sleep = original
    assert words == FAILED_WORDS
    posts = [r for r in client.session.request.requests if r[0] == "POST"]
    assert len(posts) == 2 and {r[1] for r in posts} == {"feedback"}
    assert len(client.session.request.requests) <= 3  # the two posts and one look at /info
    # An attempt waits to connect, or once connected to read: one timeout at most.
    ceiling = sum(max(connect, read) for _, _, (connect, read) in client.session.request.requests)
    assert ceiling + sum(sleeps) < 10, (ceiling, sleeps)
    assert feedback.SEND_BUDGET_SECONDS < 10


def test_the_client_the_application_makes_has_a_connect_and_read_timeout_of_two_seconds():
    client = feedback.new_client({"LANGSMITH_API_KEY": "a-key-from-the-test"})
    assert client.timeout_ms == (2000, 2000)


@pytest.mark.parametrize("error", [TypeError, AttributeError, KeyError, ValueError, RuntimeError])
def test_an_unexpected_reply_shape_from_the_client_is_the_sentence_and_not_a_server_error(error):
    class Odd(FakeLangSmith):
        def create_feedback(self, run_id=None, key="unnamed", **kwargs):
            raise error("an unexpected reply shape")

    runs = signed_run()
    client = make_client(runs, feedback=lambda: Odd(), notes={})
    done = sign(client, runs)
    assert done.status_code == 303 and runs.submitted
    assert client.get(f"{RUN}/signed").text.count(FAILED_WORDS) == 1


def test_an_unexpected_reply_shape_from_the_queue_is_the_sentence_too():
    class Odd(FakeLangSmith):
        def list_annotation_queues(self, *, name=None, **kwargs):
            return iter([SimpleNamespace(id=QUEUE_ID)])  # no name on it

    runs = signed_run()
    client = make_client(runs, feedback=lambda: Odd(), notes={})
    sign(client, runs)
    assert client.get(f"{RUN}/signed").text.count(FAILED_WORDS) == 1


def test_the_run_services_root_run_is_what_the_sign_route_sends_to_langsmith():
    import sys
    from datetime import datetime
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workflow"))
    from engine_fakes import ScriptedModels, respond
    from review_fixtures import TODAY

    from review_app.context import Services
    from review_app.drafts import DraftStore
    from workflow.runs import BriefRuns

    ls = FakeLangSmith()
    runs = BriefRuns(models=ScriptedModels(), project_id=lambda: PROJECT_ID)
    thread = runs.start(
        {"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "x", "sections": ["7"]}
    )
    end = time.monotonic() + 20
    while runs.status(thread) != "awaiting_review":
        assert time.monotonic() < end
        time.sleep(0.01)
    request = runs.review_request(thread)
    drafts = DraftStore()
    for decision in respond(request, reviewer=DANA.model_dump()).decisions:
        drafts.put_fact_decision(thread, decision)
    services = Services(runs=lambda: runs, drafts=drafts, today=lambda: TODAY, feedback=lambda: ls)
    client = make_client_for(services)
    done = client.post(
        f"/compliance-brief/runs/{thread}/sign",
        data={
            "brief_digest": request.brief_digest,
            "outcome": "returned",
            "reason": "The deadlines need another reading.",
        },
    )
    assert done.status_code == 303, done.text[:300]
    root = runs.root_run(thread)
    assert ls.feedback and {f["run_id"] for f in ls.feedback} == {root.run_id}
    assert {f["session_id"] for f in ls.feedback} == {PROJECT_ID}
    assert {f["start_time"] for f in ls.feedback} == {datetime.fromisoformat(root.started_at)}
    assert ls.added[0]["runs"][0]["run_id"] == root.run_id
    assert ls.feedback[-1]["value"] == "returned"


def test_a_send_left_going_after_the_cap_is_logged_with_what_it_had_sent_and_when_it_finished(
    monkeypatch, caplog
):
    monkeypatch.setattr(feedback, "SEND_BUDGET_SECONDS", 0.3)
    ls = FakeLangSmith()
    ls.hold = threading.Event()
    runs = signed_run()
    client = make_client(runs, feedback=lambda: ls, notes={})
    with caplog.at_level("INFO", logger="review_app.feedback"):
        sign(client, runs)
        at_the_cap = [r.getMessage() for r in caplog.records]
        assert any("still going after 0.3 seconds" in m and "0 of 3 sent" in m for m in at_the_cap)
        ls.hold.set()
        for thread in threading.enumerate():
            if thread.name == "queue-feedback":
                thread.join(5)
    late = [r for r in caplog.records if "finished after the cap" in r.getMessage()]
    assert [r.levelname for r in late] == ["INFO"]
    later = [r.getMessage() for r in late]
    assert later == [
        "The send to LangSmith finished after the cap: 3 of 3 decisions sent and the run queued"
    ]


def test_a_send_that_fails_after_the_cap_is_logged_as_a_warning(monkeypatch, caplog):
    monkeypatch.setattr(feedback, "SEND_BUDGET_SECONDS", 0.3)
    ls = FakeLangSmith(fail=["create_feedback"])
    ls.hold = threading.Event()
    runs = signed_run()
    client = make_client(runs, feedback=lambda: ls, notes={})
    with caplog.at_level("INFO", logger="review_app.feedback"):
        sign(client, runs)
        ls.hold.set()
        for thread in threading.enumerate():
            if thread.name == "queue-feedback":
                thread.join(5)
    late = [r for r in caplog.records if "finished after the cap" in r.getMessage()]
    assert [r.levelname for r in late] == ["WARNING"]
    assert late[0].getMessage().endswith("0 of 3 decisions sent and the run not queued; it failed")
