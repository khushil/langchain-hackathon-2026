"""What each reviewer has decided so far on a brief that is not yet signed, held until they sign."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from fsi_common.records import Decision, Person

PersonKey = tuple[str, str]


class DraftFileError(Exception):
    """The file that keeps pending review work cannot be opened, read or written."""


def person_key(person: Person) -> PersonKey:
    """Return what tells one signed-in person from another: the name and the role."""
    return (person.name, person.role)


@dataclass
class Draft:
    """One person's pending decisions, answers and assumptions on one brief."""

    facts: dict[str, Decision] = field(default_factory=dict)
    answers: dict[str, Decision] = field(default_factory=dict)
    assumptions: dict[str, str] = field(default_factory=dict)


class DraftStore:
    """Pending review work by run and by person, safe to use from several requests at once.

    A person's work is theirs alone: another person signed in on the same brief sees none of it,
    and cannot sign it. With a ``path`` the work is also kept in that file, so a store opened on
    it later holds the same; without one it is kept in memory only.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        """Open the store.

        Args:
            path: The database file that keeps the work; memory only when absent.

        Raises:
            DraftFileError: If the file is not a database this store wrote, or holds a decision
                that is not valid.
        """
        self._drafts: dict[tuple[str, PersonKey], Draft] = {}
        self._lock = threading.Lock()
        self._path = Path(path) if path is not None else None
        self._conn: sqlite3.Connection | None = None
        if self._path is not None:
            self._open(self._path)

    def _open(self, path: Path) -> None:
        try:
            self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS drafts (thread_id TEXT NOT NULL, "
                "person_name TEXT NOT NULL, person_role TEXT NOT NULL, kind TEXT NOT NULL, "
                "key TEXT NOT NULL, payload TEXT NOT NULL, "
                "PRIMARY KEY (thread_id, person_name, person_role, kind, key))"
            )
            rows = self._conn.execute(
                "SELECT thread_id, person_name, person_role, kind, key, payload FROM drafts"
            ).fetchall()
        except sqlite3.Error as exc:
            raise DraftFileError(f"The file {path} cannot be used as a database: {exc}") from exc
        for thread_id, name, role, kind, key, payload in rows:
            try:
                draft = self._draft(thread_id, Person(name=name, role=role))
                if kind == "assumption":
                    draft.assumptions[key] = payload
                else:
                    held = Decision.model_validate(json.loads(payload))
                    (draft.facts if kind == "fact" else draft.answers)[key] = held
            except (ValidationError, json.JSONDecodeError) as exc:
                raise DraftFileError(
                    f"The pending {kind} {key} of {name} on run {thread_id} in {path} is not "
                    f"valid: {exc}"
                ) from exc

    def _keep(self, thread_id: str, person: Person, kind: str, key: str, payload: str) -> None:
        """Write one item to the file; the lock is held by the caller."""
        self._write(
            "INSERT OR REPLACE INTO drafts VALUES (?, ?, ?, ?, ?, ?)",
            (thread_id, person.name, person.role, kind, key, payload),
        )

    def _drop(self, thread_id: str, person: Person, kind: str, key: str) -> None:
        self._write(
            "DELETE FROM drafts WHERE thread_id = ? AND person_name = ? AND person_role = ? "
            "AND kind = ? AND key = ?",
            (thread_id, person.name, person.role, kind, key),
        )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Make the writes in the block one change to the file: all of them, or none."""
        if self._conn is None:
            yield
            return
        self._write("BEGIN", ())
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._write("COMMIT", ())

    def _write(self, sql: str, values: tuple) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute(sql, values)
        except sqlite3.Error as exc:
            raise DraftFileError(
                f"The pending work could not be kept in {self._path}: {exc}"
            ) from exc

    def close(self) -> None:
        """Close the file, if there is one."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _draft(self, thread_id: str, person: Person) -> Draft:
        return self._drafts.setdefault((thread_id, person_key(person)), Draft())

    def get(self, thread_id: str, person: Person | None) -> Draft:
        """Return a copy of one person's pending work on a run, empty when there is none.

        Args:
            thread_id: The run.
            person: The person signed in, or None when nobody is.

        Returns:
            A draft the caller may read without affecting the store.
        """
        if person is None:
            return Draft()
        with self._lock:
            held = self._drafts.get((thread_id, person_key(person)), Draft())
            return Draft(dict(held.facts), dict(held.answers), dict(held.assumptions))

    def put_fact_decision(self, thread_id: str, decision: Decision) -> None:
        """Keep a decision on a fact for the person who made it, replacing their earlier one.

        Args:
            thread_id: The run.
            decision: The decision; its reviewer is the person it is kept for.

        Raises:
            DraftFileError: If the file cannot be written.
        """
        with self._lock:
            self._keep(
                thread_id,
                decision.reviewer,
                "fact",
                decision.subject_id,
                json.dumps(decision.to_json()),
            )
            self._draft(thread_id, decision.reviewer).facts[decision.subject_id] = decision

    def put_answer(self, thread_id: str, decision: Decision) -> None:
        """Keep an answer to a question; it replaces an assumption on the same question.

        Args:
            thread_id: The run.
            decision: The answer decision; its reviewer is the person it is kept for.

        Raises:
            DraftFileError: If the file cannot be written.
        """
        with self._lock:
            person, question = decision.reviewer, decision.subject_id
            with self._transaction():
                self._drop(thread_id, person, "assumption", question)
                self._keep(thread_id, person, "answer", question, json.dumps(decision.to_json()))
            draft = self._draft(thread_id, person)
            draft.answers[question] = decision
            draft.assumptions.pop(question, None)

    def put_assumption(self, thread_id: str, person: Person, question_id: str, words: str) -> None:
        """Keep a person's assumption for a question; it replaces their answer to the question.

        Args:
            thread_id: The run.
            person: The person who accepts the assumption.
            question_id: The open question accepted as an assumption.
            words: The assumption in the person's words.

        Raises:
            DraftFileError: If the file cannot be written.
        """
        with self._lock:
            with self._transaction():
                self._drop(thread_id, person, "answer", question_id)
                self._keep(thread_id, person, "assumption", question_id, words)
            draft = self._draft(thread_id, person)
            draft.assumptions[question_id] = words
            draft.answers.pop(question_id, None)

    def clear(self, thread_id: str) -> None:
        """Drop everyone's pending work on a run once it has been submitted.

        Args:
            thread_id: The run.

        Raises:
            DraftFileError: If the file cannot be written.
        """
        with self._lock:
            self._write("DELETE FROM drafts WHERE thread_id = ?", (thread_id,))
            for key in [k for k in self._drafts if k[0] == thread_id]:
                del self._drafts[key]
