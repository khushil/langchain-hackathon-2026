"""Tests of the queue call with the real LangSmith client, against a server on this machine.

The server stands in for LangSmith: it records every request, so a test can show which paths the
client used and how many times it tried. Nothing here reaches the network outside this machine.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import langsmith
import pytest

from review_app import feedback
from review_app.feedback import FAILED_WORDS, QUEUE_NAME

RUN_ID = "5d1c6f0a-6a1f-4e77-9a53-0d5b2f0d9c11"
PROJECT_ID = "9a8b7c6d-0000-4000-8000-00000000abcd"
QUEUE_ID = "3f2e1d0c-0000-4000-8000-00000000beef"
TENANT_ID = "1c2d3e4f-0000-4000-8000-000000000001"
STARTED = datetime.datetime(2026, 11, 25, 9, 0, tzinfo=datetime.UTC)
ITEMS_PATH = f"/api/v1/platform/annotation-queues/{QUEUE_ID}/items"
CURRENT_PATHS = {
    "/api/v1/info",
    "/info",
    "/api/v1/feedback",
    "/api/v1/annotation-queues",
    "/api/v1/annotation-queues?name=" + QUEUE_NAME + "&limit=100&offset=0",
    ITEMS_PATH,
}
"""Every path a signed brief's send may use; a removed path is not among them."""


class LocalLangSmith:
    """A server that answers like LangSmith for the calls a signed brief makes."""

    def __init__(self):
        self.requests: list[tuple[str, str, object]] = []
        self.on_items = "accept"  # accept, refuse, error, slow or drop
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self):
                size = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(size)
                return json.loads(raw) if raw else None

            def do_GET(self):
                owner.requests.append(("GET", self.path, None))
                if self.path.endswith("/info"):
                    return self._reply(200, {"version": "0.17.0"})
                if "/annotation-queues" in self.path:
                    return self._reply(200, [])
                return self._reply(404, {"detail": "not found"})

            def do_POST(self):
                body = self._body()
                owner.requests.append(("POST", self.path, body))
                if self.path.endswith("/items"):
                    return owner._items(self)
                if self.path.endswith("/feedback"):
                    return self._reply(200, {"id": RUN_ID})
                if self.path.endswith("/annotation-queues"):
                    return self._reply(
                        200, {"id": QUEUE_ID, "name": QUEUE_NAME, "tenant_id": TENANT_ID}
                    )
                return self._reply(404, {"detail": "not found"})

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass  # a client that gave up on a slow answer leaves a broken pipe

        self.server = Server(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def _items(self, handler):
        if self.on_items == "refuse":
            return handler._reply(403, {"detail": "this key may not use the queue"})
        if self.on_items == "error":
            return handler._reply(500, {"detail": "the queue service failed"})
        if self.on_items == "slow":
            time.sleep(1.0)
            return handler._reply(200, {"items": []})
        if self.on_items == "drop":
            handler.connection.close()
            return None
        return handler._reply(200, {"items": [{"id": "item-1"}]})

    def paths(self, method: str) -> list[str]:
        return [path for verb, path, _ in self.requests if verb == method]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    server = LocalLangSmith()
    yield server
    server.stop()


@pytest.fixture
def short_timeouts(monkeypatch):
    """Connect and read time-outs of 300 ms, for the tests that wait for a time-out or a drop."""
    monkeypatch.setattr(feedback, "CONNECT_MS", 300)
    monkeypatch.setattr(feedback, "READ_MS", 300)


def real_client(local):
    return feedback.new_client(
        {"LANGSMITH_API_KEY": "a-key-from-the-test", "LANGSMITH_ENDPOINT": local.url + "/api/v1"}
    )


def root():
    return SimpleNamespace(run_id=RUN_ID, project_id=PROJECT_ID, started_at=STARTED.isoformat())


def one_decision():
    person = SimpleNamespace(name="Dana Whitfield", role="Head of Compliance")
    sign_off = SimpleNamespace(outcome="signed", reason=None, reviewer=person, brief_id="brief:1")
    return SimpleNamespace(decisions=[], sign_off=sign_off)


def test_a_signed_brief_reaches_the_queue_by_the_items_path_and_by_no_removed_one(local):
    client = real_client(local)
    words = feedback.report_to_queue(lambda: client, root, one_decision())
    assert words is None
    [(_, _, body)] = [r for r in local.requests if r[1].endswith("/items")]
    assert body == {
        "items": [
            {
                "item_type": "RUN",
                "run_id": RUN_ID,
                "project_id": PROJECT_ID,
                "start_time": STARTED.isoformat(),
            }
        ]
    }
    assert local.paths("POST").count(ITEMS_PATH) == 1
    assert {path for _, path, _ in local.requests} <= CURRENT_PATHS


def test_a_refusal_of_the_queue_call_is_the_sentence_and_is_asked_once(local):
    local.on_items = "refuse"
    client = real_client(local)
    assert feedback.report_to_queue(lambda: client, root, one_decision()) == FAILED_WORDS
    assert local.paths("POST").count(ITEMS_PATH) == 1


def test_a_refusal_raises_the_new_permission_error(local):
    local.on_items = "refuse"
    with pytest.raises(langsmith.PermissionDeniedError):
        feedback.add_run_to_queue(real_client(local), QUEUE_ID, root())


def test_a_queue_call_that_times_out_is_the_sentence_and_is_tried_twice(local, short_timeouts):
    local.on_items = "slow"
    client = real_client(local)
    began = time.monotonic()
    assert feedback.report_to_queue(lambda: client, root, one_decision()) == FAILED_WORDS
    assert local.paths("POST").count(ITEMS_PATH) == feedback.SEND_ATTEMPTS == 2
    assert time.monotonic() - began < feedback.SEND_BUDGET_SECONDS


def test_a_timeout_raises_the_new_timeout_error(local, short_timeouts):
    local.on_items = "slow"
    with pytest.raises(langsmith.APITimeoutError):
        feedback.add_run_to_queue(real_client(local), QUEUE_ID, root())


def test_a_connection_that_fails_on_the_queue_call_is_the_sentence_and_is_tried_twice(
    local, short_timeouts
):
    local.on_items = "drop"
    client = real_client(local)
    assert feedback.report_to_queue(lambda: client, root, one_decision()) == FAILED_WORDS
    assert local.paths("POST").count(ITEMS_PATH) == 2


def test_a_server_that_cannot_be_reached_raises_the_new_connection_error(local):
    client = real_client(local)
    local.stop()
    with pytest.raises(langsmith.APIConnectionError):
        feedback.add_run_to_queue(client, QUEUE_ID, root())


def test_a_server_error_is_tried_twice_and_not_three_times(local):
    local.on_items = "error"
    with pytest.raises(langsmith.LangsmithError):
        feedback.add_run_to_queue(real_client(local), QUEUE_ID, root())
    assert local.paths("POST").count(ITEMS_PATH) == 2


def test_a_dropped_connection_is_tried_twice_and_not_three_times(local, short_timeouts):
    local.on_items = "drop"
    with pytest.raises(langsmith.LangsmithError):
        feedback.add_run_to_queue(real_client(local), QUEUE_ID, root())
    assert local.paths("POST").count(ITEMS_PATH) == 2


def test_a_start_time_without_a_zone_is_sent_as_utc(local):
    naive = SimpleNamespace(run_id=RUN_ID, project_id=PROJECT_ID, started_at="2026-11-25T09:00:00")
    feedback.add_run_to_queue(real_client(local), QUEUE_ID, naive)
    [(_, _, body)] = [r for r in local.requests if r[1].endswith("/items")]
    assert body["items"][0]["start_time"] == "2026-11-25T09:00:00+00:00"


def test_the_call_runs_to_the_end_in_a_thread_that_already_has_a_running_loop(local):
    async def inside_a_loop():
        feedback.add_run_to_queue(real_client(local), QUEUE_ID, root())

    asyncio.run(inside_a_loop())
    assert local.paths("POST").count(ITEMS_PATH) == 1


def test_a_call_that_outlasts_the_budget_stops_there(monkeypatch):
    monkeypatch.setattr(feedback, "SEND_BUDGET_SECONDS", 0.2)

    async def never():
        await asyncio.sleep(5)

    began = time.monotonic()
    with pytest.raises(TimeoutError):
        feedback.run_to_completion(never)
    assert time.monotonic() - began < 2.0
