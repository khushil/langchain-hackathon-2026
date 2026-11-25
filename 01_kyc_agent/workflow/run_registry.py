"""The files that keep the run service's state: its folder, its list of runs and their settings."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Literal, get_args

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore
from langsmith.utils import LangSmithNotFoundError

from fsi_common.evals.upload import DEFAULT_ENDPOINT
from utils.models import MAX_CONCURRENCY, tracing_enabled
from workflow.graph import GRAPH_NAME

RunStatus = Literal["running", "awaiting_review", "signed", "returned", "failed"]
CHECKPOINT_FILE, STORE_FILE, RUNS_FILE = "checkpoints.sqlite", "store.sqlite", "runs.sqlite"
LOCK_FILE = "in-use.lock"


class StateFolderError(Exception):
    """The folder that keeps the runs cannot be made or opened, or a file in it cannot be read."""


@dataclass
class Run:
    """One run as the service holds it: its configuration, request, status and failure."""

    thread_id: str
    config: dict[str, Any]
    request: dict[str, Any] = field(default_factory=dict)
    status: RunStatus = "running"
    error: str | None = None
    worker: threading.Thread | None = field(default=None, repr=False)
    project_id: str | None = None
    """The id of the trace project the run is traced to; None until it is known."""
    started_at: str | None = None
    """When the service started the run, as an ISO 8601 time with its zone."""

    @property
    def run_id(self) -> str | None:
        """The id the run's first graph run is traced under; None for a run made before ids."""
        return self.config.get("run_id")


@dataclass(frozen=True)
class RootRun:
    """Where a batch's first graph run was traced: its id, its project and when it started."""

    run_id: str | None
    project_id: str | None
    started_at: str | None


class ProjectLookup:
    """Finds the id of the trace project the environment names, once for each project.

    With tracing off nothing is looked for. A project that does not exist yet is not remembered as
    missing: the first trace creates it, and the next lookup finds it.
    """

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        make_client: Callable[[Mapping[str, str]], Any] | None = None,
    ) -> None:
        """Make a lookup.

        Args:
            env: The environment; the process's when omitted.
            make_client: Makes the LangSmith client from the environment; the real one when omitted.
        """
        self._env, self._make_client = env, make_client
        self._known: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def __call__(self) -> str | None:
        """Return the project's id, or None when tracing is off or the project is not found.

        Raises:
            LangSmithError: If LangSmith cannot be reached or refuses the request.
        """
        env = os.environ if self._env is None else self._env
        key = env.get("LANGSMITH_API_KEY") or env.get("LANGSMITH_KEY")
        if not tracing_enabled(env) or not key:
            return None
        name = env.get("LANGSMITH_PROJECT") or env.get("LANGCHAIN_PROJECT") or "default"
        endpoint = env.get("LANGSMITH_ENDPOINT", DEFAULT_ENDPOINT)
        with self._lock:
            if (endpoint, name) not in self._known:
                make = self._make_client or _real_client
                try:
                    project = make(env).read_project(project_name=name)
                except LangSmithNotFoundError:
                    return None
                self._known[(endpoint, name)] = str(project.id)
            return self._known[(endpoint, name)]


def _real_client(env: Mapping[str, str]) -> Any:
    from langsmith import Client

    key = env.get("LANGSMITH_API_KEY") or env.get("LANGSMITH_KEY")
    return Client(api_key=key, api_url=env.get("LANGSMITH_ENDPOINT", DEFAULT_ENDPOINT))


default_project_id = ProjectLookup()
"""The lookup the run service uses unless it is given another."""


class Registry:
    """The list of runs in a file: each run's request, configuration, status and failure.

    Every call is made with the owning ``KycRuns``'s lock held, so one connection serves all
    the application's threads.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        try:
            self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS runs (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
                "thread_id TEXT NOT NULL UNIQUE, request TEXT NOT NULL, metadata TEXT NOT NULL, "
                "status TEXT NOT NULL, error TEXT)"
            )
            columns = {row[1] for row in self._conn.execute("PRAGMA table_info(runs)")}
            for added in ("run_id", "project_id", "started_at"):
                if added not in columns:  # a file made before the runs kept where they were traced
                    self._conn.execute(f"ALTER TABLE runs ADD COLUMN {added} TEXT")
        except sqlite3.Error as exc:
            raise StateFolderError(
                f"The file {path} cannot be opened as a database: {exc}"
            ) from exc

    def load(self) -> list[Run]:
        """Read every run, oldest first.

        Returns:
            The runs, with their configuration rebuilt from the stored settings.

        Raises:
            StateFolderError: If the runs cannot be read, a stored request or setting is not
                valid JSON, or a status is not one a run can have; the run is named.
        """
        try:
            rows = self._conn.execute(
                "SELECT thread_id, request, metadata, status, error, run_id, project_id, "
                "started_at "
                "FROM runs ORDER BY seq"
            ).fetchall()
        except sqlite3.Error as exc:
            raise StateFolderError(f"The runs in {self._path} cannot be read: {exc}") from exc
        runs = []
        for thread_id, request, metadata, status, error, run_id, project, started in rows:
            if status not in get_args(RunStatus):
                raise StateFolderError(
                    f"Run {thread_id} in {self._path} has the status '{status}', which is not "
                    f"one of {', '.join(get_args(RunStatus))}."
                )
            try:
                runs.append(
                    Run(
                        thread_id=thread_id,
                        config=config_of(thread_id, json.loads(metadata), run_id=run_id),
                        request=json.loads(request),
                        status=status,
                        error=error,
                        project_id=project,
                        started_at=started,
                    )
                )
            except json.JSONDecodeError as exc:
                raise StateFolderError(
                    f"The stored request or settings of run {thread_id} in {self._path} cannot "
                    f"be read: {exc}"
                ) from exc
        return runs

    def add(self, run: Run) -> None:
        """Keep a new run.

        Args:
            run: The run, with its request and configuration.

        Raises:
            StateFolderError: If the file cannot be written or already holds the thread id.
        """
        self._write(
            "INSERT INTO runs (thread_id, request, metadata, status, error, run_id, project_id, "
            "started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.thread_id,
                json.dumps(run.request),
                json.dumps(run.config["metadata"]),
                run.status,
                run.error,
                run.run_id,
                run.project_id,
                run.started_at,
            ),
        )

    def update(self, run: Run) -> None:
        """Keep a run's status, failure and trace project.

        Args:
            run: The run, with its new status, failure and project.

        Raises:
            StateFolderError: If the file cannot be written.
        """
        self._write(
            "UPDATE runs SET status = ?, error = ?, project_id = ? WHERE thread_id = ?",
            (run.status, run.error, run.project_id, run.thread_id),
        )

    def _write(self, sql: str, values: tuple) -> None:
        try:
            self._conn.execute(sql, values)
        except sqlite3.Error as exc:
            raise StateFolderError(f"The run could not be kept in {self._path}: {exc}") from exc

    def close(self) -> None:
        """Close the file."""
        self._conn.close()


def config_of(
    thread_id: str, metadata: Mapping[str, Any], *, run_id: str | None = None
) -> dict[str, Any]:
    """Return the configuration the graph runs a thread with.

    Args:
        thread_id: The run's thread id.
        metadata: The number of customers and the digest of the applications the run was
            started with.
        run_id: The id to trace the graph run under, so a later step can name it; the graph
            gives its own when absent.

    Returns:
        The configuration: the thread, the graph's name, the concurrency limit, the metadata and,
        when given, the run id.
    """
    config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "run_name": GRAPH_NAME,
        "max_concurrency": MAX_CONCURRENCY,
        "metadata": dict(metadata),
    }
    if run_id is not None:
        config["run_id"] = run_id
    return config


@dataclass
class StateFolder:
    """The three files of a state folder, each opened once for use from every thread."""

    checkpointer: SqliteSaver
    store: SqliteStore
    registry: Registry
    connections: list[sqlite3.Connection]
    lock: IO[str]

    def close(self) -> None:
        """Close every file and let another server use the folder."""
        self.registry.close()
        for conn in self.connections:
            conn.close()
        self.lock.close()


def open_state_folder(folder: Path) -> StateFolder:
    """Make the folder if need be and open its checkpoint, store and run files.

    Args:
        folder: The state folder.

    Returns:
        The saver, store and registry over the folder's files, and the lock that keeps a second
        server out of the folder until ``close``.

    Raises:
        StateFolderError: If the folder cannot be made or locked, another server holds it, or a
            file in it is not a usable database.
    """
    try:
        folder.mkdir(parents=True, exist_ok=True)
        lock = (folder / LOCK_FILE).open("a")
    except OSError as exc:
        raise StateFolderError(f"The state folder {folder} cannot be made: {exc}") from exc
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        lock.close()
        raise StateFolderError(
            f"The state folder {folder} is already in use by another server; stop that server "
            "or give this one another folder."
        ) from exc
    try:
        return _open_files(folder, lock)
    except StateFolderError:
        lock.close()
        raise


def _open_files(folder: Path, lock: IO[str]) -> StateFolder:
    connections: list[sqlite3.Connection] = []
    saver_file, store_file = folder / CHECKPOINT_FILE, folder / STORE_FILE
    try:
        saver_conn = sqlite3.connect(saver_file, check_same_thread=False)
        connections.append(saver_conn)
        saver = SqliteSaver(saver_conn)
        saver.setup()
    except sqlite3.Error as exc:
        raise StateFolderError(f"The file {saver_file} is not a usable database: {exc}") from exc
    try:
        store_conn = sqlite3.connect(store_file, check_same_thread=False, isolation_level=None)
        connections.append(store_conn)
        store = SqliteStore(store_conn)
        store.setup()
    except sqlite3.Error as exc:
        raise StateFolderError(f"The file {store_file} is not a usable database: {exc}") from exc
    return StateFolder(saver, store, Registry(folder / RUNS_FILE), connections, lock)
