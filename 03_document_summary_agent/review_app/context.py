"""What every page of the topic needs: the services it calls and how it reads a run."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

from starlette.exceptions import HTTPException

from review_app.drafts import DraftFileError, DraftStore
from review_app.feedback import FeedbackClient, default_client
from review_app.library import Library, read_library
from review_app.naming import Naming
from review_app.paragraph_map import DocumentMap, build_map
from review_app.review_route import today
from review_app.service import (
    EngineMissingError,
    RunNotFoundError,
    RunsService,
    StateFolderError,
    get_runs,
)
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
    state_dir: Path | None = None
    """The folder that keeps the state, when the application is durable."""
    feedback: Callable[[], FeedbackClient | None] = default_client
    """Gives the LangSmith client the decisions on a signed brief go to; None with tracing off."""
    feedback_notes: dict[str, str] = field(default_factory=dict)
    """For each run whose decisions were not all sent, the sentence the signed page shows."""


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


STATE_ERRORS = (StateFolderError, DraftFileError)
LOG = logging.getLogger("review_app.context")
STATE_ACTION = "The server could not save your work. Tell the person who runs this server."


def state_unavailable(exc: Exception, what: str) -> HTTPException:
    """Make the answer for a state folder that could not be written.

    The file's path and the database's own words go to the log with the traceback; the person
    reads what was not done and whom to tell.

    Args:
        exc: The failure.
        what: What was not done, as a sentence without its full stop, such as "Nothing was
            recorded".

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


def naming_of(services: Services) -> Naming:
    """Return the names the pages use for firms, providers and the places facts come from."""
    return Naming.of(services.library())


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


def run_tabs(
    thread_id: str, status: str, *, has_profile: bool = False
) -> list[tuple[str, str, str]]:
    """Return the parts of a run's pages as key, label and address.

    Args:
        thread_id: The run.
        status: The run's status.
        has_profile: Whether the brief cites firm or provider facts, which are decided together.

    Returns:
        The tabs for a brief awaiting review, or for one that has been signed or returned.
    """
    facts = ("facts", "Facts", run_url(thread_id, "facts"))
    if status == "awaiting_review":
        profile = [("profile", "Firm profile", run_url(thread_id, "review", tab="profile"))]
        return [
            ("brief", "Brief", run_url(thread_id, "review")),
            *(profile if has_profile else []),
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


def document_map(
    services: Services,
    info: RunInfo,
    href_for: Callable[[str, Sequence[str]], str],
    current: str | None = None,
) -> DocumentMap | None:
    """Draw the picture of the document a run was asked to read.

    Args:
        services: The services, whose library names the sections.
        info: The run.
        href_for: Gives the address that opens a paragraph, from its anchor and first fact.
        current: The anchor of the paragraph open now, if any.

    Returns:
        The picture, or None when the run holds no accounting of the document.
    """
    document = services.library().document(info.document_id)
    titles = {s.number: s.title for s in document.sections} if document else {}
    return build_map(
        info.state, sections=info.sections, titles=titles, href_for=href_for, current=current
    )
