"""Tests for the client factory and the template function that gives a page its trace."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from jinja2 import DictLoader, Environment

from fsi_common.tracing import TraceLookup, traced_client, tracing_is_on
from fsi_common.tracing.pages import trace_view_global


def test_tracing_is_read_as_langsmith_reads_it() -> None:
    assert tracing_is_on({"LANGSMITH_TRACING": "True"})
    assert tracing_is_on({"LANGCHAIN_TRACING_V2": "true"})
    assert not tracing_is_on({"LANGSMITH_TRACING": "false"})
    assert not tracing_is_on({})


def test_there_is_no_client_with_tracing_off_or_no_key() -> None:
    assert traced_client({"LANGSMITH_API_KEY": "k"}) is None
    assert traced_client({"LANGSMITH_TRACING": "true"}) is None


class _Page:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    async def __aiter__(self):
        for item in self._items:
            yield item


class _Client:
    def __init__(self) -> None:
        self.runs = SimpleNamespace(get_url=self._url)
        self.traces = SimpleNamespace(query=self._query)

    async def _url(self, run_id: str, **kwargs: Any) -> Any:
        return SimpleNamespace(url=f"https://smith.example/{run_id}")

    async def _query(self, **kwargs: Any) -> Any:
        return _Page(
            [SimpleNamespace(trace_aggregates=SimpleNamespace(total_tokens=12, total_cost=0.5))]
        )


def _render(template: str, path_params: dict[str, str], roots: dict[str, Any]) -> str:
    lookup = TraceLookup(_Client)
    env = Environment(loader=DictLoader({"t": template}))
    env.globals["trace_view"] = trace_view_global(lookup, roots.get)
    page = env.get_template("t")
    page.render(request=SimpleNamespace(path_params=path_params))
    assert lookup.settle(5.0)
    return page.render(request=SimpleNamespace(path_params=path_params))


ROOT = SimpleNamespace(run_id="r1", project_id="p1", started_at=None)
SHOW = (
    "{% set t = trace_view() %}"
    "{% if t %}{{ t.url }}|{{ t.usage.total_tokens }}{% else %}none{% endif %}"
)


def test_a_review_page_gets_its_trace() -> None:
    assert _render(SHOW, {"thread": "th"}, {"th": ROOT}) == "https://smith.example/r1|12"


def test_a_page_that_is_not_about_a_review_gets_nothing() -> None:
    assert _render(SHOW, {}, {"th": ROOT}) == "none"


def test_an_unknown_or_untraced_review_gets_nothing() -> None:
    assert _render(SHOW, {"thread": "other"}, {"th": ROOT}) == "none"
    untraced = SimpleNamespace(run_id=None, project_id=None, started_at=None)
    assert _render(SHOW, {"thread": "th"}, {"th": untraced}) == "none"
