"""Where a review's trace is in LangSmith, and what the review has used so far.

The link comes from the run's id, project and start time, and the totals from the traces that share
the review's thread id: the run that started it and each run that resumed after a decision. Both
are read with the client's current interface.

A page never waits for LangSmith. ``TraceLookup.view`` answers at once with what it holds, and
starts the read it is missing on a thread of its own, at most one at a time for each thing it
reads. The client is made on that thread too, because its first use asks LangSmith about itself
before any request of ours, and that wait is no part of a page. A read that fails is left alone for
a while before it is tried again, so a LangSmith that hangs, refuses or limits the rate of
requests costs the page nothing. The first page of a review therefore shows no line, and the next
one shows it.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

LOG = logging.getLogger("fsi_common.tracing")
_T = TypeVar("_T")

BUDGET_SECONDS = 3.0
"""The longest one read waits for LangSmith's answer, on its own thread."""
FRESH_SECONDS = 30.0
"""How long a review's totals are kept before they are read again."""
RETRY_SECONDS = 20.0
"""How long a failed read is left alone before it is tried again."""
STUCK_SECONDS = 60.0
"""How long a read may run before another is allowed to start beside it."""
USAGE_FIELDS = ("ID", "TOTAL_TOKENS", "TOTAL_COST")
LOOKBACK = datetime.timedelta(days=31)
"""How far back a review's traces are looked for; a trace is kept for fourteen days."""


@dataclass(frozen=True)
class TraceUsage:
    """What a review's traces have used so far, as LangSmith counts them."""

    traces: int
    total_tokens: int | None
    total_cost: float | None


@dataclass(frozen=True)
class TraceView:
    """What a page shows about a review's trace: the link, and the totals when known."""

    url: str | None
    usage: TraceUsage | None


class NoClientError(Exception):
    """There is no client to read with: tracing is off or no key is set."""


def expected_errors() -> tuple[type[BaseException], ...]:
    """The failures a read is expected to meet: LangSmith's own, the network's and a time-out."""
    errors: list[type[BaseException]] = [OSError, ValueError, TimeoutError]
    try:
        import langsmith
        import langsmith.utils
    except ImportError:
        return tuple(errors)
    errors += [langsmith.utils.LangSmithError, langsmith.LangsmithError]
    return tuple(errors)


def run_to_completion(make: Callable[[], Awaitable[_T]], budget_s: float = BUDGET_SECONDS) -> _T:
    """Run a coroutine to the end from synchronous code, for no longer than the budget.

    Args:
        make: Makes the coroutine; called in the thread that runs it.
        budget_s: The longest to wait, in seconds.

    Returns:
        What the coroutine returned.

    Raises:
        TimeoutError: If the coroutine had not finished when the budget ran out.
    """

    async def bounded() -> _T:
        return await asyncio.wait_for(make(), timeout=budget_s)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(bounded())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, bounded()).result()


def _sum_of(traces: list[Any]) -> TraceUsage:
    """Add up the tokens and cost LangSmith counts for each trace of a review."""
    tokens: list[int] = []
    costs: list[float] = []
    for trace in traces:
        totals = getattr(trace, "trace_aggregates", None)
        if totals is None:
            continue
        if getattr(totals, "total_tokens", None) is not None:
            tokens.append(int(totals.total_tokens))
        if getattr(totals, "total_cost", None) is not None:
            costs.append(float(totals.total_cost))
    return TraceUsage(
        traces=len(traces),
        total_tokens=sum(tokens) if tokens else None,
        total_cost=sum(costs) if costs else None,
    )


class TraceLookup:
    """Holds what LangSmith said about each review's trace, and reads more in the background.

    A link never changes, so it is read once. Totals grow while a review runs, so they are read
    again after ``FRESH_SECONDS``; until the new answer arrives the old one is shown.
    """

    def __init__(
        self,
        make_client: Callable[[], Any | None],
        *,
        clock: Callable[[], float] = time.monotonic,
        budget_s: float = BUDGET_SECONDS,
    ) -> None:
        """Make a lookup.

        Args:
            make_client: Gives the LangSmith client, or None when tracing is off. It is called on
                the reading thread, never on a page's.
            clock: The time in seconds, for the lookup's own expiry.
            budget_s: The longest one read waits for LangSmith's answer.
        """
        self._make_client, self._clock, self._budget = make_client, clock, budget_s
        self._made: Any | None = None
        self._urls: dict[str, str] = {}
        self._usage: dict[str, tuple[float, TraceUsage]] = {}
        self._failed_at: dict[str, float] = {}
        self._running: dict[str, tuple[float, threading.Thread]] = {}
        self._unexpected: list[BaseException] = []
        self._lock = threading.Lock()
        self._make_lock = threading.Lock()

    def view(
        self,
        *,
        thread_id: str,
        run_id: str | None,
        project_id: str | None,
        started_at: str | None,
    ) -> TraceView | None:
        """Return the link and totals held for one review's trace, and read what is missing.

        Args:
            thread_id: The review's thread id.
            run_id: The id the review's first graph run was traced under.
            project_id: The trace project's id.
            started_at: When the run started, as an ISO time, or None when unknown.

        Returns:
            The link and totals held, with a part None where it is not known yet; None when
            nothing is held. It never waits for LangSmith.
        """
        if not run_id or not project_id or '"' in thread_id:
            return None
        with self._lock:
            url = self._urls.get(run_id)
            held = self._usage.get(thread_id)
        if url is None:
            self._start(f"url:{run_id}", self._read_url, run_id, project_id, started_at)
        if held is None or self._clock() - held[0] >= FRESH_SECONDS:
            self._start(f"usage:{thread_id}", self._read_usage, thread_id, project_id)
        usage = held[1] if held else None
        if url is None and usage is None:
            return None
        return TraceView(url=url, usage=usage)

    def settle(self, timeout_s: float = 5.0, *, raise_errors: bool = False) -> bool:
        """Wait for the reads in progress to finish; for a test or a shutdown, never for a page.

        Args:
            timeout_s: The longest to wait for each read.
            raise_errors: Raise the first failure that was not an expected one.

        Returns:
            Whether every read finished within the time.

        Raises:
            BaseException: The first unexpected failure, when ``raise_errors`` is set.
        """
        with self._lock:
            threads = [thread for _, thread in self._running.values()]
        for thread in threads:
            thread.join(timeout_s)
        done = not any(thread.is_alive() for thread in threads)
        if raise_errors and self._unexpected:
            raise self._unexpected[0]
        return done

    def _start(self, key: str, read: Callable[..., None], *args: Any) -> None:
        """Start the read of one thing on a thread of its own, unless one is under way or failed."""
        now = self._clock()
        with self._lock:
            failed = self._failed_at.get(key)
            if failed is not None and now - failed < RETRY_SECONDS:
                return
            running = self._running.get(key)
            if running is not None and (running[1].is_alive() and now - running[0] < STUCK_SECONDS):
                return
            thread = threading.Thread(target=self._guarded, args=(key, read, *args), daemon=True)
            self._running[key] = (now, thread)
        thread.start()

    def _guarded(self, key: str, read: Callable[..., None], *args: Any) -> None:
        try:
            read(*args)
        except NoClientError:
            self._fail(key)
        except expected_errors():
            LOG.exception("The read %s from LangSmith failed", key)
            self._fail(key)
        except BaseException as error:  # noqa: BLE001 - kept for a test, logged, never a page's
            LOG.exception("The read %s from LangSmith failed unexpectedly", key)
            with self._lock:
                self._unexpected.append(error)
            self._fail(key)

    def _fail(self, key: str) -> None:
        with self._lock:
            self._failed_at[key] = self._clock()

    def _client(self) -> Any:
        with self._lock:
            if self._made is not None:
                return self._made
        with self._make_lock:
            with self._lock:
                if self._made is not None:
                    return self._made
            made = self._make_client()
            if made is None:
                raise NoClientError
            with self._lock:
                self._made = made
            return made

    def _read_url(self, run_id: str, project_id: str, started_at: str | None) -> None:
        client = self._client()
        extra = {"start_time": started_at} if started_at else {}
        answer = run_to_completion(
            lambda: client.runs.get_url(run_id, project_id=project_id, trace_id=run_id, **extra),
            self._budget,
        )
        url = getattr(answer, "url", None)
        if not url:
            raise OSError(f"LangSmith gave no link for run {run_id}.")
        with self._lock:
            self._urls[run_id] = url

    def _read_usage(self, thread_id: str, project_id: str) -> None:
        client = self._client()
        traces = run_to_completion(
            lambda: self._review_traces(client, thread_id, project_id), self._budget
        )
        with self._lock:
            self._usage[thread_id] = (self._clock(), _sum_of(traces))

    @staticmethod
    async def _review_traces(client: Any, thread_id: str, project_id: str) -> list[Any]:
        """Every trace of one review: its first run and each run that resumed after a decision."""
        since = datetime.datetime.now(datetime.UTC) - LOOKBACK
        page = await client.traces.query(
            project_id=project_id,
            min_start_time=since.isoformat(),
            trace_filter=f'eq(thread_id, "{thread_id}")',
            selects=list(USAGE_FIELDS),
            page_size=100,
        )
        return [trace async for trace in page]
