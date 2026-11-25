"""A batch's pages link to its trace in LangSmith and show what the review has used.

The line is read from LangSmith in the background: a page shows what is held and never waits, so
each case asks once, lets the read finish and asks again.
"""

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from kyc_fakes import ScriptedReader
from langsmith_planted import KEY, MODES, environment, start_server
from support import (
    BASE,
    SMALL,
    make_client,
    make_services,
    new_runs,
    settle_all,
    start_run,
    text_of,
)

from fsi_common.tracing import TraceLookup, traced_client
from review_app.plugin import trace_of
from review_app.service import RunNotFoundError
from workflow.runs import KycRuns

PAGES = ("review", "screenings", "signoff", "application", "run", "signed")
LINK = 'href="https://eu.smith.example/p/proj-2/r/root-4"'


class _Page:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    async def __aiter__(self):
        for item in self._items:
            yield item


def _trace(tokens: int, cost: float) -> Any:
    return SimpleNamespace(trace_aggregates=SimpleNamespace(total_tokens=tokens, total_cost=cost))


class _Client:
    def __init__(self, cost: float = 1.5) -> None:
        self.runs = SimpleNamespace(get_url=self._url)
        self.traces = SimpleNamespace(query=self._query)
        self.asked: list[str] = []
        self.cost = cost

    async def _url(self, run_id: str, **kwargs: Any) -> Any:
        self.asked.append("url")
        return SimpleNamespace(url=f"https://eu.smith.example/p/{kwargs['project_id']}/r/{run_id}")

    async def _query(self, **kwargs: Any) -> Any:
        self.asked.append("stats")
        return _Page([_trace(5000, self.cost / 2), _trace(4876, self.cost / 2)])


class _Traced:
    """The real run service, saying its first run was traced in a project."""

    def __init__(self, real: Any, *, traced: bool = True) -> None:
        self._real, self._traced = real, traced

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    def root_run(self, thread_id: str) -> Any:
        if not self._traced:
            return SimpleNamespace(run_id=None, project_id=None, started_at=None)
        return SimpleNamespace(
            run_id="root-4", project_id="proj-2", started_at="2026-11-25T09:00:00+00:00"
        )


@pytest.fixture()
def gate():
    event = threading.Event()
    yield event
    event.set()


def _world(page: str, lookup: TraceLookup, gate: threading.Event, *, traced: bool = True):
    """A client over one batch in the state the page needs, and the address of the page."""
    if page == "run":
        real = KycRuns(models=ScriptedReader(gate=gate))
        thread = real.start({"request": "Review the applications", "customer_ids": SMALL})
        address = f"{BASE}/runs/{thread}"
    else:
        real = new_runs()
        thread = start_run(real, SMALL)
        address = f"{BASE}/runs/{thread}/{'review' if page == 'signed' else page}"
        if page == "application":
            address = f"{BASE}/runs/{thread}/applications/CUST-001"
    runs = _Traced(real, traced=traced)
    client = make_client(runs, services=make_services(runs, traces=lookup))
    if page == "signed":
        settle_all(client, real, thread)
        digest = real.review_request(thread).brief_digest
        client.post(
            f"{BASE}/runs/{thread}/sign", data={"brief_digest": digest, "outcome": "signed"}
        )
        address = f"{BASE}/runs/{thread}/signed"
    return client, address, thread


def _second_visit(client, address: str, lookup: TraceLookup) -> str:
    first = client.get(address)
    assert first.status_code == 200
    assert lookup.settle(5.0, raise_errors=True)
    second = client.get(address)
    assert second.status_code == 200
    return second.text


@pytest.mark.parametrize("page", PAGES)
def test_every_page_links_to_the_batch_trace_and_shows_its_tokens_and_cost(page, gate):
    langsmith = _Client()
    lookup = TraceLookup(lambda: langsmith)
    client, address, thread = _world(page, lookup, gate)
    html = _second_visit(client, address, lookup)
    assert LINK in html and 'rel="noopener"' in html
    text = text_of(html)
    assert "Trace in LangSmith" in text
    assert "9,876 tokens; LangSmith estimates about $1.50" in text
    assert "list prices" not in text
    assert "stats" in langsmith.asked


@pytest.mark.parametrize("page", PAGES)
def test_the_first_visit_shows_no_line_and_does_not_wait_for_langsmith(page, gate):
    lookup = TraceLookup(lambda: _Client())
    client, address, _ = _world(page, lookup, gate)
    assert 'data-hook="trace"' not in client.get(address).text
    assert lookup.settle(5.0)


@pytest.mark.parametrize("page", PAGES)
def test_a_cost_under_a_cent_is_said_so(page, gate):
    lookup = TraceLookup(lambda: _Client(cost=0.0069))
    client, address, _ = _world(page, lookup, gate)
    text = text_of(_second_visit(client, address, lookup))
    assert "LangSmith estimates under $0.01" in text
    assert "$0.00" not in text


def test_the_cost_says_in_a_hover_that_it_is_an_estimate_and_not_a_bill(gate):
    lookup = TraceLookup(lambda: _Client())
    client, address, _ = _world("review", lookup, gate)
    assert "it is not a bill" in _second_visit(client, address, lookup)


@pytest.mark.parametrize("page", PAGES)
def test_a_batch_the_engine_did_not_trace_shows_no_link_and_asks_nothing(page, gate):
    langsmith = _Client()
    lookup = TraceLookup(lambda: langsmith)
    client, address, _ = _world(page, lookup, gate, traced=False)
    assert 'data-hook="trace"' not in _second_visit(client, address, lookup)
    assert langsmith.asked == []


@pytest.mark.parametrize("page", PAGES)
def test_with_tracing_off_the_page_has_no_link(page, gate):
    lookup = TraceLookup(lambda: None)
    client, address, _ = _world(page, lookup, gate)
    assert 'data-hook="trace"' not in _second_visit(client, address, lookup)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("page", PAGES)
def test_a_page_answers_within_half_a_second_whatever_langsmith_does(page, mode, gate, caplog):
    server = start_server(mode)
    try:
        env = environment(server)
        lookup = TraceLookup(lambda: traced_client(env))
        client, address, _ = _world(page, lookup, gate)
        for _ in range(3):
            started = time.monotonic()
            answer = client.get(address)
            assert time.monotonic() - started < 0.5
            assert answer.status_code == 200
            assert 'data-hook="trace"' not in answer.text
            assert KEY not in answer.text
        assert KEY not in caplog.text
    finally:
        server.shutdown()


def test_a_batch_the_service_does_not_know_has_no_root():
    runs = new_runs()
    services = make_services(runs)
    with pytest.raises(RunNotFoundError):
        runs.root_run("nothing-here")
    assert trace_of(services, "nothing-here") is None
