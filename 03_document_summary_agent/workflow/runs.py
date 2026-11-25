"""The run service the application calls: start a run, watch it, put it to a reviewer, resume it."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from context.reader import read_document
from context.tables import read_tables
from utils.records import FACT_CONTEXT
from utils.state import BriefRequest, BriefState, ReviewRequest, ReviewResponse
from workflow.errors import InvalidRequestError
from workflow.graph import build_graph
from workflow.requests import selected_sections
from workflow.review import validate_response
from workflow.run_registry import (
    Run,
    RunStatus,
    StateFolder,
    StateFolderError,
    config_of,
    open_state_folder,
)
from workflow.sections import ModelSource

LOG = logging.getLogger("workflow.runs")
REQUIRED = ("document_id", "firm_id", "request")
STOPPED_WORDS = "The server stopped before the brief reached its review; start the brief again."


class RunNotFoundError(Exception):
    """There is no run with this thread id."""


class NotAwaitingReviewError(Exception):
    """The run is not stopped at the review, so there is nothing to read or submit."""


class RunInProgressError(Exception):
    """A run is still running, and one run is up to thirteen headless processes."""


class BriefRuns:
    """Owns the compiled graph, its checkpointer and its store; safe for one application process.

    Each ``start`` runs the graph in a background thread up to the review interrupt; ``submit``
    resumes it from the reviewer's response. Decisions are kept in the store, so a later run on the
    same firm and document reads them.
    """

    def __init__(
        self,
        *,
        models: ModelSource | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
        state_dir: Path | str | None = None,
    ) -> None:
        """Compile the graph with a checkpointer and a store.

        Args:
            models: Gives the chat model for a role; ``get_model`` when omitted.
            checkpointer: Defaults to an in-memory saver.
            store: Defaults to an in-memory store.
            state_dir: A folder that keeps the runs, their checkpoints and the decisions in files,
                so a service opened on the same folder later finds them. Without it everything is
                kept in memory. A run a stopped server left running is settled from its
                checkpoint: waiting for its reviewer, signed or returned, or failed.

        Raises:
            StateFolderError: If ``state_dir`` is given with a ``checkpointer`` or a ``store``,
                the folder cannot be made, or a file in it is not a database this service wrote.
        """
        self._folder: StateFolder | None = None
        if state_dir is not None:
            if checkpointer is not None or store is not None:
                raise StateFolderError(
                    "A state folder keeps its own checkpointer and store; "
                    "do not give a checkpointer or a store with it."
                )
            self._folder = open_state_folder(Path(state_dir))
            checkpointer, store = self._folder.checkpointer, self._folder.store
        options: dict[str, Any] = {
            "checkpointer": checkpointer or InMemorySaver(),
            "store": store or InMemoryStore(),
        }
        if models is not None:
            options["models"] = models
        self._graph = build_graph(**options)
        self._runs: dict[str, Run] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()
        if self._folder is not None:
            for run in self._folder.registry.load():
                self._settle_after_restart(run)
                self._runs[run.thread_id] = run
                self._order.append(run.thread_id)

    def _settle_after_restart(self, run: Run) -> None:
        """Say where a run left ``running`` by a stopped server really stands, and keep it."""
        if run.status != "running":
            return
        run.status, run.error = self._standing(run)
        self._keep(run)

    def _standing(self, run: Run) -> tuple[RunStatus, str | None]:
        try:
            state = self._graph.get_state(run.config)
        except Exception:  # an unreadable checkpoint must fail this run, not stop the service
            LOG.exception("Run %s: the checkpoint could not be read at start", run.thread_id)
            return "failed", STOPPED_WORDS
        if state.next and any(task.interrupts for task in state.tasks):
            return "awaiting_review", None
        sign_off = state.values.get("sign_off")
        if not state.next and sign_off:
            return ("signed" if sign_off["outcome"] == "signed" else "returned"), None
        return "failed", STOPPED_WORDS

    def _keep(self, run: Run) -> None:
        """Write a run's status to the file, if there is one; the lock is held by the caller."""
        if self._folder is not None:
            self._folder.registry.update(run)

    def close(self) -> None:
        """Close the files of a state folder; do nothing for a service kept in memory.

        Call it only when no run is running: a run still proceeding would fail on its next write.
        """
        with self._lock:
            if self._folder is not None:
                self._folder.close()

    def start(self, request: BriefRequest) -> str:
        """Start a run in a background thread and return its thread id at once.

        Args:
            request: The ``BriefRequest``; an optional ``sections`` key lists the section numbers
                to read, and every section is read when it is absent.

        Returns:
            The thread id.

        Raises:
            InvalidRequestError: If the request lacks a field, or holds an empty ``sections`` list.
            DocumentNotFoundError: If the document is not in the library.
            FirmNotFoundError: If the firm is not in the firm table.
            RunInProgressError: If a run is still running.
        """
        missing = [name for name in REQUIRED if not request.get(name)]
        if missing:
            raise InvalidRequestError(f"The request lacks {', '.join(missing)}.")
        document = read_document(request["document_id"])
        read_tables(request["firm_id"])
        selected_sections(document, request)
        with self._lock:
            if any(run.status == "running" for run in self._runs.values()):
                raise RunInProgressError("A run is still running; wait for it to reach the review.")
            thread_id = str(uuid.uuid4())
            run = Run(
                thread_id=thread_id,
                config=self._config(thread_id, request, document),
                request=dict(request),
            )
            if self._folder is not None:
                self._folder.registry.add(run)
            self._runs[thread_id] = run
            self._order.append(thread_id)
            run.worker = threading.Thread(
                target=self._execute, args=(run, {"request": dict(request)}), daemon=True
            )
            run.worker.start()
        return thread_id

    @staticmethod
    def _config(thread_id: str, request: Mapping[str, Any], document: Any) -> dict[str, Any]:
        return config_of(
            thread_id,
            {
                "document_id": request["document_id"],
                "firm_id": request["firm_id"],
                "document_digest": document.source.digest,
            },
        )

    def _get(self, thread_id: str) -> Run:
        with self._lock:
            run = self._runs.get(thread_id)
        if run is None:
            raise RunNotFoundError(f"There is no run {thread_id}.")
        return run

    def _execute(self, run: Run, payload: Any, config: dict[str, Any] | None = None) -> None:
        try:
            self._graph.invoke(payload, config or run.config)
            status, error = self._settled(run), None
        except Exception as exc:  # the thread must record any failure, and never raise
            LOG.exception("Run %s failed", run.thread_id)
            status, error = self._after_failure(run), str(exc) or type(exc).__name__
        with self._lock:
            run.status, run.error = status, error
            try:
                self._keep(run)
            except StateFolderError:  # the next start settles the run again from its checkpoint
                LOG.exception(
                    "Run %s: its status %s could not be kept in the file", run.thread_id, status
                )

    def _after_failure(self, run: Run) -> RunStatus:
        """Say where a run stands after the graph raised: still at the review, or failed.

        A resume that raises leaves the checkpoint at the review interrupt, so the reviewer's
        response can be sent again; any other failure ends the run.
        """
        try:
            state = self._graph.get_state(run.config)
        except Exception:  # the status must still be recorded when the checkpoint cannot be read
            LOG.exception("Run %s: the checkpoint could not be read after a failure", run.thread_id)
            return "failed"
        waiting = bool(state.next) and any(task.interrupts for task in state.tasks)
        return "awaiting_review" if waiting else "failed"

    def _settled(self, run: Run) -> RunStatus:
        state = self._graph.get_state(run.config)
        if state.next:
            return "awaiting_review"
        sign_off = state.values.get("sign_off")
        if sign_off:
            return "signed" if sign_off["outcome"] == "signed" else "returned"
        raise RuntimeError("The run ended without a review or a sign-off.")

    def status(self, thread_id: str) -> RunStatus:
        """Return where a run stands.

        Args:
            thread_id: The run's thread id.

        Returns:
            ``running``, ``awaiting_review``, ``signed``, ``returned`` or ``failed``.

        Raises:
            RunNotFoundError: If the thread id is unknown.
        """
        run = self._get(thread_id)
        with self._lock:
            return run.status

    def review_request(self, thread_id: str) -> ReviewRequest:
        """Return the brief as the reviewer is shown it.

        Args:
            thread_id: The run's thread id.

        Returns:
            The review request held in the run's interrupt.

        Raises:
            RunNotFoundError: If the thread id is unknown.
            NotAwaitingReviewError: If the run is not stopped at the review.
        """
        run = self._get(thread_id)
        if self.status(thread_id) != "awaiting_review":
            raise NotAwaitingReviewError(f"Run {thread_id} is {self.status(thread_id)}.")
        task = self._graph.get_state(run.config).tasks[0]
        return ReviewRequest.model_validate(task.interrupts[0].value, context=FACT_CONTEXT)

    def submit(self, thread_id: str, response: ReviewResponse) -> RunStatus:
        """Give the graph the reviewer's response and run it on to its end or the next review.

        The response is checked against what the reviewer was shown before anything is stored;
        a response that does not answer it is refused and the run still waits.

        Args:
            thread_id: The run's thread id.
            response: The reviewer, their decisions and, when they signed or returned it, the
                sign-off.

        Returns:
            The status after the graph has run on: ``signed``, ``returned``, or
            ``awaiting_review`` when no sign-off was sent.

        Raises:
            RunNotFoundError: If the thread id is unknown.
            NotAwaitingReviewError: If the run is not stopped at the review.
            ReviewMismatchError: If the response does not answer the request shown.
        """
        run = self._get(thread_id)
        request = self.review_request(thread_id)
        validate_response(response, request, self._graph.get_state(run.config).values)
        with self._lock:
            if run.status != "awaiting_review":
                raise NotAwaitingReviewError(f"Run {thread_id} is {run.status}.")
            run.status = "running"
            try:
                self._keep(run)
            except StateFolderError:
                run.status = "awaiting_review"
                raise
        config = {
            **run.config,
            "metadata": {**run.config["metadata"], "reviewer": response.reviewer.name},
        }
        self._execute(run, Command(resume=response.model_dump(mode="json", by_alias=True)), config)
        return self.status(thread_id)

    def result(self, thread_id: str) -> BriefState:
        """Return the run's state as it stands.

        Args:
            thread_id: The run's thread id.

        Returns:
            The state at the run's latest checkpoint; before the graph has written one, the state
            holds the request the run was started with, so a caller can always name the run.

        Raises:
            RunNotFoundError: If the thread id is unknown.
        """
        run = self._get(thread_id)
        state = self._graph.get_state(run.config).values
        if "request" not in state:
            return {**state, "request": dict(run.request)}
        return state

    def error(self, thread_id: str) -> str | None:
        """Return the failure of a failed run, in words.

        Args:
            thread_id: The run's thread id.

        Returns:
            The failure, or None when the run has not failed.

        Raises:
            RunNotFoundError: If the thread id is unknown.
        """
        run = self._get(thread_id)
        with self._lock:
            return run.error

    def list_runs(self) -> list[str]:
        """Return every run's thread id, newest first.

        Returns:
            The thread ids.
        """
        with self._lock:
            return list(reversed(self._order))
