"""The files that keep the run service's state: its folder, its list of runs and their settings."""

from __future__ import annotations

import fcntl
import json
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Literal, get_args

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore

from utils.models import MAX_CONCURRENCY
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


class Registry:
    """The list of runs in a file: each run's request, configuration, status and failure.

    Every call is made with the owning ``BriefRuns``'s lock held, so one connection serves all
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
                "SELECT thread_id, request, metadata, status, error FROM runs ORDER BY seq"
            ).fetchall()
        except sqlite3.Error as exc:
            raise StateFolderError(f"The runs in {self._path} cannot be read: {exc}") from exc
        runs = []
        for thread_id, request, metadata, status, error in rows:
            if status not in get_args(RunStatus):
                raise StateFolderError(
                    f"Run {thread_id} in {self._path} has the status '{status}', which is not "
                    f"one of {', '.join(get_args(RunStatus))}."
                )
            try:
                runs.append(
                    Run(
                        thread_id=thread_id,
                        config=config_of(thread_id, json.loads(metadata)),
                        request=json.loads(request),
                        status=status,
                        error=error,
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
            "INSERT INTO runs (thread_id, request, metadata, status, error) VALUES (?, ?, ?, ?, ?)",
            (
                run.thread_id,
                json.dumps(run.request),
                json.dumps(run.config["metadata"]),
                run.status,
                run.error,
            ),
        )

    def update(self, run: Run) -> None:
        """Keep a run's status and failure.

        Args:
            run: The run, with its new status and failure.

        Raises:
            StateFolderError: If the file cannot be written.
        """
        self._write(
            "UPDATE runs SET status = ?, error = ? WHERE thread_id = ?",
            (run.status, run.error, run.thread_id),
        )

    def _write(self, sql: str, values: tuple) -> None:
        try:
            self._conn.execute(sql, values)
        except sqlite3.Error as exc:
            raise StateFolderError(f"The run could not be kept in {self._path}: {exc}") from exc

    def close(self) -> None:
        """Close the file."""
        self._conn.close()


def config_of(thread_id: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Return the configuration the graph runs a thread with.

    Args:
        thread_id: The run's thread id.
        metadata: The document, firm and document digest the run was started with.

    Returns:
        The configuration: the thread, the graph's name, the concurrency limit and the metadata.
    """
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": GRAPH_NAME,
        "max_concurrency": MAX_CONCURRENCY,
        "metadata": dict(metadata),
    }


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
