"""What every page of the topic needs: the services it calls and how it reads a run."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from starlette.exceptions import HTTPException

from fsi_common.app.rendering import long_date
from review_app.drafts import DraftFileError, DraftStore
from utils import db
from utils.review import ReviewRequest
from workflow.run_registry import StateFolderError
from workflow.runs import MonitorRuns, RunNotFoundError
from workflow.state import MonitorState

PREFIX = "/transaction-monitoring"
STATUS_WORDS = {
    "running": "Being assessed",
    "awaiting_review": "Waiting for a reviewer",
    "signed": "Signed",
    "returned": "Returned",
    "failed": "Stopped",
}
STATE_ERRORS = (StateFolderError, DraftFileError)
LOG = logging.getLogger("review_app.context")
STATE_ACTION = "The server could not save your work. Tell the person who runs this server."
NO_ANSWER_HELD = "No saved answer is held for part of this run, so it could not be assessed here."
_HASH = re.compile(r"\s*\b(?:sha256:)?[0-9a-f]{32,}\b")

_runs: MonitorRuns | None = None


def get_runs() -> MonitorRuns:
    """Return the run service, making the engine's on first use.

    Returns:
        The service the pages call.
    """
    global _runs
    if _runs is None:
        _runs = MonitorRuns()
    return _runs


def today() -> str:
    """Return today's date as ``YYYY-MM-DD``."""
    return date.today().isoformat()


@dataclass
class Services:
    """The run service, the held decisions and the clock the pages use."""

    runs: Callable[[], MonitorRuns] = get_runs
    drafts: DraftStore = field(default_factory=DraftStore)
    today: Callable[[], str] = today
    state_dir: Path | None = None
    """The folder that keeps the state, when the application is durable."""


def customers() -> list[tuple[str, str]]:
    """Return the customers the start page offers, as (user id, name), in table order."""
    return [(row["user_id"], row["name"]) for row in db.table("customer_profiles")]


def customer_name(user_id: str) -> str:
    """Return a customer's name, or the id when the profile table has none."""
    row = db.get("customer_profiles", user_id=user_id)
    return row["name"] if row else user_id


def window_words(start: str | None, end: str | None) -> str:
    """Say a window of a stream in words.

    Args:
        start: The first day, as ``YYYY-MM-DD``, or None.
        end: The day the window stops before, or None.

    Returns:
        ``whole stream``, ``from 19 October 2026``, ``before 19 October 2026`` or both.
    """
    first, last = (long_date(v[:10]) if v else None for v in (start, end))
    if first and last:
        return f"from {first} up to {last}"
    if first:
        return f"from {first}"
    if last:
        return f"before {last}"
    return "whole stream"


@dataclass(frozen=True)
class RunInfo:
    """One run as the pages name it: the customer and the window asked for."""

    thread_id: str
    status: str
    user_id: str
    customer: str
    start: str | None
    end: str | None
    state: MonitorState

    @property
    def label(self) -> str:
        """The run in words, for a link."""
        return f"{self.customer}, {window_words(self.start, self.end)}"


def plain_error(text: str | None) -> str:
    """Put an engine failure in the words a reviewer reads: no hash, no internal mode name.

    Args:
        text: What the engine gave as the reason, or None when it gave none.

    Returns:
        A sentence. A missing saved answer is said as that; any other reason keeps its words
        with the long identifiers taken out.
    """
    if not text:
        return "The engine gave no reason."
    if "no recording for request" in text:
        return NO_ANSWER_HELD
    plain = _HASH.sub("", text).strip()
    return plain[:1].upper() + plain[1:]


def state_unavailable(exc: Exception, what: str) -> HTTPException:
    """Make the answer for a state folder that could not be written.

    The file's path and the database's own words go to the log with the traceback; the person
    reads what was not done and whom to tell.

    Args:
        exc: The failure.
        what: What was not done, as a sentence without its full stop.

    Returns:
        A 503 whose reason says what was not done and what to do.
    """
    LOG.error("The state folder could not be written: %s", exc, exc_info=exc)
    return HTTPException(503, f"{what}. {STATE_ACTION}")


def run_url(thread_id: str, *parts: str, **query: str) -> str:
    """Return the address of a page of a run.

    Args:
        thread_id: The run.
        *parts: Path parts after the run, such as ``review``.
        **query: Query parameters; empty values are left out.

    Returns:
        The address, with the query when there is one.
    """
    path = "/".join([PREFIX, "runs", thread_id, *parts])
    kept = {k: v for k, v in query.items() if v}
    return path + (f"?{urlencode(kept)}" if kept else "")


def runs_of(services: Services) -> MonitorRuns:
    """Return the run service."""
    return services.runs()


def read_run(services: Services, thread_id: str) -> RunInfo:
    """Read a run's status and request.

    Args:
        services: The services.
        thread_id: The run.

    Returns:
        The run.

    Raises:
        HTTPException: 404, if the engine does not know the run.
    """
    runs = runs_of(services)
    try:
        status = runs.status(thread_id)
        state = runs.result(thread_id)
    except RunNotFoundError as exc:
        raise HTTPException(404, f"There is no run {thread_id}.") from exc
    request = state.get("request", {})
    user_id = request.get("user_id", "")
    return RunInfo(
        thread_id=thread_id,
        status=status,
        user_id=user_id,
        customer=customer_name(user_id),
        start=request.get("start"),
        end=request.get("end"),
        state=state,
    )


def earlier_decisions(request: ReviewRequest) -> dict:
    """Return the decisions the brief's history holds, by id, for questions another run settled.

    Args:
        request: The request the reviewer was shown.

    Returns:
        The history's decisions by their ids.
    """
    return {d.id: d for d in request.history}
