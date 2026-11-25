"""The engine's run service as the pages use it, and the errors that service raises."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from utils.state import BriefRequest, BriefState, ReviewRequest, ReviewResponse

try:
    from context.errors import DocumentNotFoundError, FirmNotFoundError
    from workflow.errors import InvalidRequestError, UnknownSectionError
    from workflow.runs import (
        BriefRuns,
        NotAwaitingReviewError,
        RunInProgressError,
        RunNotFoundError,
        StateFolderError,
    )
except ModuleNotFoundError as exc:
    if exc.name not in {
        "workflow",
        "workflow.runs",
        "workflow.errors",
        "context",
        "context.errors",
    }:
        raise
    BriefRuns = None

    class RunNotFoundError(LookupError):  # type: ignore[no-redef]
        """The thread id names no run."""

    class NotAwaitingReviewError(RuntimeError):  # type: ignore[no-redef]
        """The run is not waiting for a reviewer."""

    class RunInProgressError(RuntimeError):  # type: ignore[no-redef]
        """A run is still being written, and only one runs at a time."""

    class StateFolderError(RuntimeError):  # type: ignore[no-redef]
        """The folder that keeps the runs cannot be used."""

    class InvalidRequestError(ValueError):  # type: ignore[no-redef]
        """The request lacks a field a run needs."""

    class UnknownSectionError(ValueError):  # type: ignore[no-redef]
        """The request asks for a section the document does not have."""

    class DocumentNotFoundError(LookupError):  # type: ignore[no-redef]
        """The document is not in the library."""

    class FirmNotFoundError(LookupError):  # type: ignore[no-redef]
        """The firm is not in the firm table."""


class EngineMissingError(RuntimeError):
    """The engine's run service is not part of this build, so no run can be started or read."""


RunStatus = Literal["running", "awaiting_review", "signed", "returned", "failed"]


class RunsService(Protocol):
    """What the pages need from the engine's ``BriefRuns``."""

    def start(self, request: BriefRequest | dict[str, Any]) -> str: ...

    def status(self, thread_id: str) -> RunStatus: ...

    def review_request(self, thread_id: str) -> ReviewRequest: ...

    def submit(self, thread_id: str, response: ReviewResponse) -> RunStatus: ...

    def root_run(self, thread_id: str) -> Any: ...

    def result(self, thread_id: str) -> BriefState: ...

    def error(self, thread_id: str) -> str | None: ...

    def list_runs(self) -> list[str]: ...


_runs: RunsService | None = None


def get_runs() -> RunsService:
    """Return the run service, making the engine's on first use.

    Returns:
        The service the pages call.

    Raises:
        EngineMissingError: If the engine's ``workflow.runs`` is not part of this build.
    """
    global _runs
    if _runs is None:
        if BriefRuns is None:
            raise EngineMissingError(
                "The engine that writes briefs is not part of this build, so no brief can be "
                "started or read here."
            )
        _runs = BriefRuns()
    return _runs


def use_runs(runs: RunsService | None) -> None:
    """Replace the run service, for tests; None makes the next call build the engine's.

    Args:
        runs: The service to use.
    """
    global _runs
    _runs = runs
