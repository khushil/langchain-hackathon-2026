"""The engine's run service as the pages use it, and the errors that service raises."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from context.errors import ApplicationNotFoundError
from utils.kyc_state import KycRequest, KycState, ReviewRequest, ReviewResponse
from workflow.errors import InvalidRequestError
from workflow.reading import ModelSource
from workflow.runs import (
    KycRuns,
    NotAwaitingReviewError,
    RunInProgressError,
    RunNotFoundError,
    StateFolderError,
)

__all__ = [
    "ApplicationNotFoundError",
    "EngineMissingError",
    "InvalidRequestError",
    "NotAwaitingReviewError",
    "RunInProgressError",
    "RunNotFoundError",
    "RunsService",
    "StateFolderError",
    "get_runs",
    "make_runs",
    "use_models",
    "use_runs",
]

RunStatus = Literal["running", "awaiting_review", "signed", "returned", "failed"]
_models: ModelSource | None = None


class EngineMissingError(RuntimeError):
    """The engine's run service is not part of this build, so no run can be started or read."""


class RunsService(Protocol):
    """What the pages need from the engine's ``KycRuns``."""

    def start(self, request: KycRequest | dict[str, Any]) -> str: ...

    def status(self, thread_id: str) -> RunStatus: ...

    def review_request(self, thread_id: str) -> ReviewRequest: ...

    def submit(self, thread_id: str, response: ReviewResponse) -> RunStatus: ...

    def result(self, thread_id: str) -> KycState: ...

    def error(self, thread_id: str) -> str | None: ...

    def root_run(self, thread_id: str) -> Any: ...

    def list_runs(self) -> list[str]: ...


def use_models(models: ModelSource | None) -> None:
    """Choose where the engine's model calls go, for the one place that makes runs.

    Args:
        models: Gives the chat model for a role; None gives the topic's own ``get_model``.
    """
    global _models
    _models = models


def make_runs(state_dir: Any = None) -> KycRuns:
    """Make the engine's run service, on the chosen models and the chosen state folder.

    Args:
        state_dir: A folder that keeps the runs and decisions in files; memory when absent.

    Returns:
        The run service.
    """
    options: dict[str, Any] = {} if _models is None else {"models": _models}
    return KycRuns(state_dir=state_dir, **options)


_runs: RunsService | None = None


def get_runs() -> RunsService:
    """Return the run service, making the engine's on first use.

    Returns:
        The service the pages call.
    """
    global _runs
    if _runs is None:
        _runs = make_runs()
    return _runs


def use_runs(runs: RunsService | None) -> None:
    """Replace the run service, for tests; None makes the next call build the engine's.

    Args:
        runs: The service to use.
    """
    global _runs
    _runs = runs
