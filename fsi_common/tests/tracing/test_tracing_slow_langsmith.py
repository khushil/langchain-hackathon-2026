"""A page never waits for LangSmith: the real client against a server that hangs or refuses."""

from __future__ import annotations

import time

import pytest
from langsmith_planted import KEY, MODES, environment, start_server

from fsi_common.tracing import TraceLookup, traced_client

LIMIT_SECONDS = 0.5


@pytest.mark.parametrize("mode", MODES)
def test_every_ask_answers_within_half_a_second_and_never_shows_a_key(mode, caplog) -> None:
    server = start_server(mode)
    try:
        env = environment(server)
        lookup = TraceLookup(lambda: traced_client(env))
        for _ in range(4):
            started = time.monotonic()
            view = lookup.view(thread_id="t-1", run_id="r-1", project_id="p-1", started_at=None)
            assert time.monotonic() - started < LIMIT_SECONDS
            assert view is None
            time.sleep(0.05)
        assert KEY not in caplog.text
    finally:
        server.shutdown()


@pytest.mark.parametrize("mode", ["error", "rate-limit"])
def test_a_refusing_langsmith_is_read_once_and_then_left_alone_for_a_while(mode) -> None:
    server = start_server(mode)
    try:
        env = environment(server)
        lookup = TraceLookup(lambda: traced_client(env))
        lookup.view(thread_id="t-1", run_id="r-1", project_id="p-1", started_at=None)
        assert lookup.settle(30.0)
        for _ in range(5):
            started = time.monotonic()
            assert (
                lookup.view(thread_id="t-1", run_id="r-1", project_id="p-1", started_at=None)
                is None
            )
            assert time.monotonic() - started < LIMIT_SECONDS
        assert lookup.settle(1.0)
    finally:
        server.shutdown()
