"""What every page of the topic needs: the services it calls and how it reads a run."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from starlette.exceptions import HTTPException

from fsi_common.records import Decision
from review_app.drafts import DraftFileError, DraftStore
from review_app.service import (
    EngineMissingError,
    RunNotFoundError,
    RunsService,
    StateFolderError,
    get_runs,
)
from utils import db
from utils.kyc_state import KycState

PREFIX = "/kyc"
STATUS_WORDS = {
    "running": "Being read",
    "awaiting_review": "Waiting for a reviewer",
    "signed": "Signed",
    "returned": "Returned",
    "failed": "Stopped",
}
STATE_ERRORS = (StateFolderError, DraftFileError)
STATE_ACTION = "The server could not save your work. Tell the person who runs this server."
LOG = logging.getLogger("review_app.context")
_HASH = re.compile(r"\s*\b(?:sha256:)?[0-9a-f]{32,}\b")
NO_ANSWER_HELD = "No saved answer is held for part of this batch, so it could not be read here."


def today() -> str:
    """Return today's date as ``YYYY-MM-DD``."""
    return date.today().isoformat()


@dataclass
class Services:
    """The run service, the held decisions and the clock the pages use."""

    runs: Callable[[], RunsService] = get_runs
    drafts: DraftStore = field(default_factory=DraftStore)
    today: Callable[[], str] = today
    state_dir: Path | None = None
    """The folder that keeps the state, when the application is durable."""


@dataclass(frozen=True)
class RunInfo:
    """One run as the pages name it: its status, its customers and its state."""

    thread_id: str
    status: str
    customers: tuple[str, ...]
    state: KycState

    @property
    def label(self) -> str:
        """The run in words, for a link."""
        count = len(self.customers)
        every = count == len(db.table("applications"))
        return (
            f"All {count} applications"
            if every
            else f"{count} application" + ("" if count == 1 else "s")
        )


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
        *parts: Path parts after the run, such as ``applications`` and ``CUST-003``.
        **query: Query parameters; empty values are left out.

    Returns:
        The address, with the query when there is one.
    """
    path = "/".join([PREFIX, "runs", thread_id, *parts])
    kept = {k: v for k, v in query.items() if v}
    return path + (f"?{urlencode(kept)}" if kept else "")


def runs_of(services: Services) -> RunsService:
    """Return the run service, or stop the page with a message in words when there is none.

    Args:
        services: The services.

    Returns:
        The run service.

    Raises:
        HTTPException: 503, if the engine is not part of this build.
    """
    try:
        return services.runs()
    except EngineMissingError as exc:
        raise HTTPException(503, str(exc)) from exc


def run_tabs(thread_id: str, status: str) -> list[tuple[str, str, str]]:
    """Return the parts of a run's pages as key, label and address.

    Args:
        thread_id: The run.
        status: The run's status.

    Returns:
        The tabs for a batch waiting for review, or for one that has been signed or returned.
    """
    screenings = ("screenings", "Screenings", run_url(thread_id, "screenings"))
    if status == "awaiting_review":
        return [
            ("applications", "Applications", run_url(thread_id, "review")),
            screenings,
            ("signoff", "Sign-off", run_url(thread_id, "signoff")),
        ]
    return [("signed", "Sign-off record", run_url(thread_id, "signed")), screenings]


def read_run(services: Services, thread_id: str) -> RunInfo:
    """Read a run's status and the customers it was asked to read.

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
    held = state.get("request", {}).get("customer_ids")
    customers = tuple(held) if held else _all_customers(state)
    return RunInfo(thread_id, status, customers, state)


def _all_customers(state: KycState) -> tuple[str, ...]:
    found = [u["anchor"].partition(":")[2] for u in state.get("units", {}).values()]
    rows = sorted(a for a in found if "/" not in a)
    return tuple(rows) if rows else ()


def earlier_decisions(
    services: Services, thread_id: str, wanted: Sequence[str]
) -> dict[str, Decision]:
    """Find decisions another finished batch holds, by their ids.

    A question another batch has answered arrives on this one as settled, naming that answer by
    id only. A decision's id is made from its content, so one id names one record wherever it is
    held, and no batch can supply a different answer under it.

    Args:
        services: The services.
        thread_id: The run being read, which is never searched.
        wanted: The ids of the decisions to find.

    Returns:
        The decisions found, by id; an id no finished batch holds is left out.
    """
    missing = set(wanted)
    found: dict[str, Decision] = {}
    if not missing:
        return found
    runs = runs_of(services)
    for other in runs.list_runs():
        if other == thread_id or runs.status(other) not in {"signed", "returned"}:
            continue
        held = runs.result(other).get("decisions", {}) or {}
        for decision_id in sorted(missing & set(held)):
            found[decision_id] = Decision.model_validate(held[decision_id])
        missing -= set(found)
        if not missing:
            break
    return found
