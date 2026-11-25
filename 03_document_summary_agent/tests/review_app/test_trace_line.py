"""A brief's pages link to its trace in LangSmith and show what the review has used.

The line is read from LangSmith in the background: a page shows what is held and never waits, so
each case asks once, lets the read finish and asks again.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from langsmith_planted import KEY, MODES, environment, start_server
from review_fakes import FakeRuns, examples_review
from review_fixtures import TODAY, make_client_for
from review_helpers import BASE, RUN, settle_everything, text_of

from fsi_common.tracing import TraceLookup, traced_client
from review_app.context import Services
from review_app.drafts import DraftStore
from review_app.plugin import trace_of
from review_app.service import RunNotFoundError

LINK = 'href="https://eu.smith.example/o/t/projects/p/proj-3/r/root-9"'
PAGES = ("review", "facts", "signed", "run")


class _Page:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    async def __aiter__(self):
        for item in self._items:
            yield item


def _trace(tokens: int, cost: float) -> Any:
    return SimpleNamespace(trace_aggregates=SimpleNamespace(total_tokens=tokens, total_cost=cost))


class _Client:
    def __init__(self, cost: float = 0.4231) -> None:
        self.runs = SimpleNamespace(get_url=self._url)
        self.traces = SimpleNamespace(query=self._query)
        self.asked: list[tuple[str, str]] = []
        self.cost = cost

    async def _url(self, run_id: str, **kwargs: Any) -> Any:
        self.asked.append(("url", run_id))
        return SimpleNamespace(
            url=f"https://eu.smith.example/o/t/projects/p/{kwargs['project_id']}/r/{run_id}"
        )

    async def _query(self, **kwargs: Any) -> Any:
        self.asked.append(("stats", kwargs["trace_filter"]))
        return _Page([_trace(20000, self.cost / 2), _trace(28210, self.cost / 2)])


def _services(runs: FakeRuns, lookup: TraceLookup) -> Services:
    return Services(runs=lambda: runs, drafts=DraftStore(), today=lambda: TODAY, traces=lookup)


def _world(page: str, lookup: TraceLookup, *, traced: bool = True):
    """A client over one run in the state the page needs, and the address of the page."""
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=examples_review())
    if page == "run":
        runs.add(
            "run-4",
            "running",
            request={"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "x"},
        )
    if traced:
        for thread in ("run-1", "run-4"):
            if thread in runs._runs:
                runs.roots[thread] = SimpleNamespace(
                    run_id="root-9", project_id="proj-3", started_at="2026-11-25T09:00:00+00:00"
                )
    c = make_client_for(_services(runs, lookup))
    if page == "signed":
        review = settle_everything(c, runs)
        c.post(
            f"{RUN}/sign", data={"brief_digest": review.request.brief_digest, "outcome": "signed"}
        )
    thread = "run-4" if page == "run" else "run-1"
    return c, f"{BASE}/runs/{thread}" + ("" if page == "run" else f"/{page}")


def _second_visit(c, path: str, lookup: TraceLookup) -> str:
    first = c.get(path)
    assert first.status_code == 200
    assert lookup.settle(5.0, raise_errors=True)
    second = c.get(path)
    assert second.status_code == 200
    return second.text


@pytest.mark.parametrize("page", PAGES)
def test_every_page_links_to_the_brief_trace_and_shows_its_tokens_and_cost(page):
    langsmith = _Client()
    lookup = TraceLookup(lambda: langsmith)
    c, path = _world(page, lookup)
    html = _second_visit(c, path, lookup)
    assert LINK in html
    assert 'target="_blank"' in html and 'rel="noopener"' in html
    text = text_of(html)
    assert "Trace in LangSmith" in text
    assert "48,210 tokens; LangSmith estimates about $0.42" in text
    assert "list prices" not in text
    thread = "run-4" if page == "run" else "run-1"
    assert ("stats", f'eq(thread_id, "{thread}")') in langsmith.asked


@pytest.mark.parametrize("page", PAGES)
def test_the_first_visit_shows_no_line_and_does_not_wait_for_langsmith(page):
    lookup = TraceLookup(lambda: _Client())
    c, path = _world(page, lookup)
    html = c.get(path).text
    assert 'data-hook="trace"' not in html
    assert lookup.settle(5.0)


@pytest.mark.parametrize("page", PAGES)
def test_a_cost_under_a_cent_is_said_so(page):
    lookup = TraceLookup(lambda: _Client(cost=0.0069))
    c, path = _world(page, lookup)
    text = text_of(_second_visit(c, path, lookup))
    assert "LangSmith estimates under $0.01" in text
    assert "$0.00" not in text


def test_the_cost_says_in_a_hover_that_it_is_an_estimate_and_not_a_bill():
    lookup = TraceLookup(lambda: _Client())
    c, path = _world("review", lookup)
    html = _second_visit(c, path, lookup)
    assert "it is not a bill" in html


@pytest.mark.parametrize("page", PAGES)
def test_a_brief_that_was_not_traced_shows_no_link_and_asks_nothing(page):
    langsmith = _Client()
    lookup = TraceLookup(lambda: langsmith)
    c, path = _world(page, lookup, traced=False)
    assert 'data-hook="trace"' not in _second_visit(c, path, lookup)
    assert langsmith.asked == []


@pytest.mark.parametrize("page", PAGES)
def test_with_tracing_off_the_page_has_no_link(page):
    lookup = TraceLookup(lambda: None)
    c, path = _world(page, lookup)
    assert 'data-hook="trace"' not in _second_visit(c, path, lookup)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("page", PAGES)
def test_a_page_answers_within_half_a_second_whatever_langsmith_does(page, mode, caplog):
    server = start_server(mode)
    try:
        env = environment(server)
        lookup = TraceLookup(lambda: traced_client(env))
        c, path = _world(page, lookup)
        for _ in range(3):
            started = time.monotonic()
            answer = c.get(path)
            assert time.monotonic() - started < 0.5
            assert answer.status_code == 200
            assert 'data-hook="trace"' not in answer.text
            assert KEY not in answer.text
        assert KEY not in caplog.text
    finally:
        server.shutdown()


def test_a_review_the_service_does_not_know_has_no_root():
    runs = FakeRuns()
    services = _services(runs, TraceLookup(lambda: None))
    with pytest.raises(RunNotFoundError):
        runs.root_run("nothing-here")
    assert trace_of(services, "nothing-here") is None
