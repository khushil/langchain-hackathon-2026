"""What reviewers decided on policy assessments, kept in files beside the application's state."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from pydantic import ValidationError

from fsi_common.records import Decision, SignOff


class PolicyRecordsError(Exception):
    """The files that keep decisions on policy assessments cannot be read or written."""


class PolicyRecords:
    """Decisions and sign-offs by corpus, safe to use from several requests at once.

    With a folder they are written as one line of JSON each under ``policy/<corpus>/`` and read
    back when the store is next used; without one they are kept in memory only. A decision is
    never edited: a later one on the same assessment by anyone replaces it in what is shown, and
    the earlier line stays in the file.
    """

    def __init__(self, folder: Path | None = None) -> None:
        """Make the store.

        Args:
            folder: The application's state folder, or None to keep records in memory.
        """
        self._folder = folder
        self._lock = threading.Lock()
        self._decisions: dict[str, list[Decision]] = {}
        self._sign_offs: dict[str, list[SignOff]] = {}
        self._loaded: set[str] = set()

    def _path(self, corpus: str, name: str) -> Path | None:
        return None if self._folder is None else self._folder / "policy" / corpus / name

    def _load(self, corpus: str) -> None:
        if corpus in self._loaded:
            return
        self._decisions[corpus] = self._read(corpus, "decisions.jsonl", Decision)
        self._sign_offs[corpus] = self._read(corpus, "sign_offs.jsonl", SignOff)
        self._loaded.add(corpus)

    def _read(self, corpus: str, name: str, record: type) -> list:
        path = self._path(corpus, name)
        if path is None or not path.exists():
            return []
        try:
            lines = path.read_text("utf-8").splitlines()
            return [record.model_validate(json.loads(line)) for line in lines if line.strip()]
        except (OSError, ValueError, ValidationError) as exc:
            raise PolicyRecordsError(f"The file {path} cannot be read: {exc}") from exc

    def _append(self, corpus: str, name: str, record: Decision | SignOff) -> None:
        path = self._path(corpus, name)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record.to_json(), ensure_ascii=False) + "\n")
        except OSError as exc:
            raise PolicyRecordsError(f"The file {path} cannot be written: {exc}") from exc

    def decisions(self, corpus: str) -> dict[str, Decision]:
        """Return the latest decision on each assessment, by the assessment's id.

        Args:
            corpus: The corpus's name.

        Returns:
            The decisions.

        Raises:
            PolicyRecordsError: If the file cannot be read.
        """
        with self._lock:
            self._load(corpus)
            return {d.subject_id: d for d in self._decisions[corpus]}

    def put_decision(self, corpus: str, decision: Decision) -> None:
        """Keep a person's decision.

        Args:
            corpus: The corpus's name.
            decision: The decision the review route built.

        Raises:
            PolicyRecordsError: If the file cannot be written; nothing is kept then.
        """
        with self._lock:
            self._load(corpus)
            self._append(corpus, "decisions.jsonl", decision)
            self._decisions[corpus].append(decision)

    def sign_off(self, corpus: str, brief_id: str) -> SignOff | None:
        """Return the latest sign-off or return of a gap report, or None.

        Args:
            corpus: The corpus's name.
            brief_id: The gap report's id.

        Returns:
            The sign-off, or None when nobody has signed or returned that report.

        Raises:
            PolicyRecordsError: If the file cannot be read.
        """
        with self._lock:
            self._load(corpus)
            held = [s for s in self._sign_offs[corpus] if s.brief_id == brief_id]
            return held[-1] if held else None

    def put_sign_off(self, corpus: str, sign_off: SignOff) -> None:
        """Keep a person's sign-off or return of a gap report.

        Args:
            corpus: The corpus's name.
            sign_off: The sign-off the review route built.

        Raises:
            PolicyRecordsError: If the file cannot be written; nothing is kept then.
        """
        with self._lock:
            self._load(corpus)
            self._append(corpus, "sign_offs.jsonl", sign_off)
            self._sign_offs[corpus].append(sign_off)
