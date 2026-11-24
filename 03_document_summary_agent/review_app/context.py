"""What every page of the topic needs: the services it calls and how it reads a run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlencode

from starlette.exceptions import HTTPException

from review_app.drafts import DraftStore
from review_app.library import Library, read_library
from review_app.review_route import today
from review_app.service import EngineMissingError, RunNotFoundError, RunsService, get_runs
from utils.state import BriefState

PREFIX = "/compliance-brief"
STATUS_WORDS = {
    "running": "Being written",
    "awaiting_review": "Waiting for a reviewer",
    "signed": "Signed",
    "returned": "Returned",
    "failed": "Stopped",
}


@dataclass
class Services:
    """The run service, the library, the held decisions and the clock the pages use."""

    runs: Callable[[], RunsService] = get_runs
    library: Callable[[], Library] = read_library
    drafts: DraftStore = field(default_factory=DraftStore)
    today: Callable[[], str] = today


@dataclass(frozen=True)
class RunInfo:
    """One run as the pages name it: the document, the firm and the sections asked for."""

    thread_id: str
    status: str
    document_id: str
    document_title: str
    firm_id: str
    firm_name: str
    sections: tuple[str, ...] | None
    state: BriefState

    @property
    def label(self) -> str:
        """The run in words, for a link."""
        part = f", section {', '.join(self.sections)}" if self.sections else ""
        return f"{self.document_id} for {self.firm_name}{part}"


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
        The tabs for a brief awaiting review, or for one that has been signed or returned.
    """
    facts = ("facts", "Facts", run_url(thread_id, "facts"))
    if status == "awaiting_review":
        return [
            ("brief", "Brief", run_url(thread_id, "review")),
            ("questions", "Open questions", run_url(thread_id, "review", tab="questions")),
            facts,
            ("signoff", "Sign-off", run_url(thread_id, "review", tab="signoff")),
        ]
    return [("signed", "Sign-off record", run_url(thread_id, "signed")), facts]


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
    library = services.library()
    sections = request.get("sections")
    return RunInfo(
        thread_id=thread_id,
        status=status,
        document_id=request.get("document_id", ""),
        document_title=library.document_title(request.get("document_id", "")),
        firm_id=request.get("firm_id", ""),
        firm_name=library.firm_name(request.get("firm_id", "")),
        sections=tuple(sections) if sections else None,
        state=state,
    )
