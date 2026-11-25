"""What every page of the topic needs: the services it calls and how it reads a run."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

from starlette.exceptions import HTTPException

from fsi_common.records import Decision
from fsi_common.tracing import TraceLookup, traced_client
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
    traces: TraceLookup = field(default_factory=lambda: TraceLookup(traced_client))
    """Reads each brief's trace link and totals from LangSmith; reads nothing with tracing off."""


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


NO_ANSWER_HELD = "No saved answer is held for part of this brief, so it could not be written here."
_HASH = re.compile(r"\s*\b(?:sha256:)?[0-9a-f]{32,}\b")


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


def earlier_decisions(
    services: Services, thread_id: str, wanted: Sequence[str]
) -> dict[str, Decision]:
    """Find decisions an earlier brief holds, by their ids.

    A question another brief has answered arrives on this brief as settled, naming that answer by
    id only; the answer itself is in the state of the brief that settled it. This reads every
    finished brief but the one being read, whatever its firm, document or age, and takes a
    decision by its id alone. That is safe because a decision's id is made from its content, so
    one id names one record wherever it is held; no brief can supply a different answer under it.

    Args:
        services: The services.
        thread_id: The run being read, which is never searched.
        wanted: The ids of the decisions to find.

    Returns:
        The decisions found, by id; an id no finished brief holds is left out.
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


def carried_decision_ids(services: Services, info: RunInfo) -> set[str]:
    """Find the decisions of a finished brief that an earlier brief had already made.

    A decision carried into a later brief keeps its id, so a decision of this brief that also
    stands in the state of a brief started before it was not made on this one.

    Args:
        services: The services.
        info: The finished run.

    Returns:
        The ids of those decisions.
    """
    held = set(info.state.get("decisions", {}) or {})
    runs = runs_of(services)
    order = runs.list_runs()  # newest first
    earlier = order[order.index(info.thread_id) + 1 :] if info.thread_id in order else []
    carried: set[str] = set()
    for other in earlier:
        if runs.status(other) not in {"signed", "returned"}:
            continue
        carried |= held & set(runs.result(other).get("decisions", {}) or {})
        if carried == held:
            break
    return carried


def document_map(
    services: Services,
    info: RunInfo,
    href_for: Callable[[str, Sequence[str]], str],
    current: str | None = None,
    settled: Mapping[str, str] | None = None,
) -> DocumentMap | None:
    """Draw the picture of the document a run was asked to read.

    Args:
        services: The services, whose library names the sections.
        info: The run.
        href_for: Gives the address that opens a paragraph, from its anchor and first fact.
        current: The anchor of the paragraph open now, if any.
        settled: How each question a person has settled was settled, by question id; the others
            are drawn as open.

    Returns:
        The picture, or None when the run holds no accounting of the document.
    """
    document = services.library().document(info.document_id)
    titles = {s.number: s.title for s in document.sections} if document else {}
    return build_map(
        info.state,
        sections=info.sections,
        titles=titles,
        href_for=href_for,
        current=current,
        settled=settled,
    )
