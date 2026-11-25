"""Tests for the trace link and totals a page shows, against a fake LangSmith client.

A page never waits for LangSmith: the lookup answers with what it holds and reads the rest in the
background, so each test first asks, then lets the background read finish, then asks again.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest

from fsi_common.tracing.lookup import FRESH_SECONDS, RETRY_SECONDS, TraceLookup, TraceUsage

RUN, PROJECT, THREAD = "run-1", "project-1", "thread-1"
STARTED = "2026-11-25T09:00:00+00:00"


class _Page:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    async def __aiter__(self):
        for item in self._items:
            yield item


class FakeRuns:
    def __init__(self, owner: FakeClient) -> None:
        self._owner = owner

    async def get_url(self, run_id: str, **kwargs: Any) -> Any:
        self._owner.url_calls.append((run_id, kwargs))
        if self._owner.url_error:
            raise self._owner.url_error
        await asyncio.sleep(self._owner.delay)
        return SimpleNamespace(url=f"https://smith.example/r/{run_id}")


class FakeTraces:
    def __init__(self, owner: FakeClient) -> None:
        self._owner = owner

    async def query(self, **kwargs: Any) -> Any:
        self._owner.stats_calls.append((kwargs["trace_filter"], kwargs))
        if self._owner.stats_error:
            raise self._owner.stats_error
        total = 1000 * len(self._owner.stats_calls)
        return _Page(
            [
                SimpleNamespace(
                    trace_aggregates=SimpleNamespace(total_tokens=total - 400, total_cost=0.1)
                ),
                SimpleNamespace(
                    trace_aggregates=SimpleNamespace(total_tokens=400, total_cost=0.15)
                ),
            ]
        )


class FakeClient:
    def __init__(self) -> None:
        self.url_calls: list[tuple[str, dict[str, Any]]] = []
        self.stats_calls: list[tuple[str, dict[str, Any]]] = []
        self.url_error: Exception | None = None
        self.stats_error: Exception | None = None
        self.delay = 0.0
        self.runs = FakeRuns(self)
        self.traces = FakeTraces(self)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _ask(lookup: TraceLookup, **changes: Any) -> Any:
    args = {"thread_id": THREAD, "run_id": RUN, "project_id": PROJECT, "started_at": STARTED}
    args.update(changes)
    return lookup.view(**args)


def _settled(lookup: TraceLookup, **changes: Any) -> Any:
    """Ask, let what the ask started finish, and ask again."""
    _ask(lookup, **changes)
    assert lookup.settle(5.0)
    return _ask(lookup, **changes)


def test_the_first_ask_holds_nothing_and_does_not_wait() -> None:
    client = FakeClient()
    client.delay = 0.3
    lookup = TraceLookup(lambda: client)
    started = time.monotonic()
    assert _ask(lookup) is None
    assert time.monotonic() - started < 0.1
    assert lookup.settle(5.0)


def test_the_link_names_the_run_its_project_and_trace_and_the_start_time() -> None:
    client = FakeClient()
    view = _settled(TraceLookup(lambda: client))
    assert view.url == "https://smith.example/r/run-1"
    assert client.url_calls == [
        (RUN, {"project_id": PROJECT, "trace_id": RUN, "start_time": STARTED})
    ]


def test_the_totals_come_from_the_review_thread() -> None:
    client = FakeClient()
    view = _settled(TraceLookup(lambda: client))
    assert view.usage == TraceUsage(traces=2, total_tokens=1000, total_cost=0.25)
    flt, kwargs = client.stats_calls[0]
    assert flt == f'eq(thread_id, "{THREAD}")'
    assert kwargs["project_id"] == PROJECT
    assert "TOTAL_TOKENS" in kwargs["selects"] and "TOTAL_COST" in kwargs["selects"]


def test_a_thread_id_that_could_break_the_filter_is_not_looked_up() -> None:
    client = FakeClient()
    lookup = TraceLookup(lambda: client)
    assert _settled(lookup, thread_id='x") or eq(thread_id, "y') is None
    assert client.stats_calls == [] and client.url_calls == []


def test_a_link_is_read_once_and_totals_are_kept_while_fresh() -> None:
    client, clock = FakeClient(), Clock()
    lookup = TraceLookup(lambda: client, clock=clock)
    _settled(lookup)
    clock.now += FRESH_SECONDS - 1
    _settled(lookup)
    assert len(client.url_calls) == 1
    assert len(client.stats_calls) == 1


def test_stale_totals_are_shown_at_once_and_read_again_behind_the_page() -> None:
    client, clock = FakeClient(), Clock()
    lookup = TraceLookup(lambda: client, clock=clock)
    first = _settled(lookup)
    clock.now += FRESH_SECONDS + 1
    second = _ask(lookup)
    assert second.usage == first.usage
    assert lookup.settle(5.0)
    assert len(client.stats_calls) == 2
    assert _ask(lookup).usage.total_tokens == 2000


def test_no_client_no_run_or_no_project_gives_nothing_and_asks_nothing() -> None:
    client = FakeClient()
    assert _settled(TraceLookup(lambda: None)) is None
    assert _settled(TraceLookup(lambda: client), run_id=None) is None
    assert _settled(TraceLookup(lambda: client), project_id=None) is None
    assert client.url_calls == [] and client.stats_calls == []


def test_a_refusal_leaves_the_part_out_and_never_raises() -> None:
    client = FakeClient()
    client.url_error = OSError("unreachable")
    view = _settled(TraceLookup(lambda: client))
    assert view.url is None and view.usage is not None
    client.stats_error = ValueError("bad")
    assert _settled(TraceLookup(lambda: client)) is None


def test_a_failed_lookup_is_left_alone_for_a_while_then_tried_again() -> None:
    client, clock = FakeClient(), Clock()
    client.url_error = OSError("down")
    lookup = TraceLookup(lambda: client, clock=clock)
    _settled(lookup)
    _settled(lookup)
    assert len(client.url_calls) == 1
    clock.now += RETRY_SECONDS + 1
    client.url_error = None
    assert _settled(lookup).url is not None
    assert len(client.url_calls) == 2


def test_a_slow_answer_is_given_up_within_the_budget_and_never_held_up_a_page() -> None:
    client = FakeClient()
    client.delay = 5.0
    lookup = TraceLookup(lambda: client, budget_s=0.2)
    started = time.monotonic()
    assert _ask(lookup) is None
    assert time.monotonic() - started < 0.1
    assert lookup.settle(5.0)
    assert _ask(lookup).url is None


def test_a_client_that_takes_long_to_make_does_not_hold_up_a_page() -> None:
    def slow() -> FakeClient:
        time.sleep(0.5)
        return FakeClient()

    lookup = TraceLookup(slow)
    started = time.monotonic()
    assert _ask(lookup) is None
    assert time.monotonic() - started < 0.1
    assert lookup.settle(5.0)
    assert _ask(lookup).url is not None


def test_it_works_from_inside_a_running_event_loop() -> None:
    client = FakeClient()
    lookup = TraceLookup(lambda: client)

    async def inside() -> Any:
        _ask(lookup)
        return await asyncio.to_thread(lookup.settle, 5.0)

    assert asyncio.run(inside())
    assert _ask(lookup).url is not None


def test_a_client_that_cannot_be_made_gives_nothing() -> None:
    def broken() -> Any:
        raise OSError("no key")

    assert _settled(TraceLookup(broken)) is None


def test_a_reply_without_a_url_leaves_the_link_out() -> None:
    client = FakeClient()

    async def no_url(run_id: str, **kwargs: Any) -> Any:
        return SimpleNamespace(url=None)

    client.runs.get_url = no_url
    view = _settled(TraceLookup(lambda: client))
    assert view.url is None and view.usage is not None


def test_a_reply_without_totals_counts_the_traces_and_leaves_the_sums_out() -> None:
    client = FakeClient()

    async def no_usage(**kwargs: Any) -> Any:
        return _Page([SimpleNamespace(trace_aggregates=None)])

    client.traces.query = no_usage
    view = _settled(TraceLookup(lambda: client))
    assert view.url is not None
    assert view.usage == TraceUsage(traces=1, total_tokens=None, total_cost=None)


def test_the_client_is_made_once_and_only_when_there_is_one() -> None:
    state = {"ready": False, "made": 0}

    def make() -> FakeClient | None:
        if not state["ready"]:
            return None
        state["made"] += 1
        return FakeClient()

    clock = Clock()
    lookup = TraceLookup(make, clock=clock)
    assert _settled(lookup) is None
    state["ready"] = True
    clock.now += RETRY_SECONDS + 1
    assert _settled(lookup).url is not None
    clock.now += FRESH_SECONDS + 1
    _settled(lookup)
    assert state["made"] == 1


def test_a_bug_in_the_client_is_not_hidden_as_an_expected_failure() -> None:
    client = FakeClient()

    async def broken(run_id: str, **kwargs: Any) -> Any:
        raise AttributeError("the interface changed")

    client.runs.get_url = broken
    lookup = TraceLookup(lambda: client)
    _ask(lookup)
    with pytest.raises(AttributeError):
        lookup.settle(5.0, raise_errors=True)


def test_at_most_one_read_of_each_thing_runs_at_a_time() -> None:
    client = FakeClient()
    client.delay = 1.0
    lookup = TraceLookup(lambda: client, budget_s=5.0)
    for _ in range(5):
        _ask(lookup)
        time.sleep(0.02)
    assert lookup.settle(5.0)
    assert len(client.url_calls) == 1
    assert len(client.stats_calls) == 1
