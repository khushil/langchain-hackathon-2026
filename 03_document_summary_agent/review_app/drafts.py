"""What each reviewer has decided so far on a brief that is not yet signed, held until they sign."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from fsi_common.records import Decision, Person

PersonKey = tuple[str, str]


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
    and cannot sign it.
    """

    def __init__(self) -> None:
        self._drafts: dict[tuple[str, PersonKey], Draft] = {}
        self._lock = threading.Lock()

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
        """
        with self._lock:
            self._draft(thread_id, decision.reviewer).facts[decision.subject_id] = decision

    def put_answer(self, thread_id: str, decision: Decision) -> None:
        """Keep an answer to a question; it replaces an assumption on the same question.

        Args:
            thread_id: The run.
            decision: The answer decision; its reviewer is the person it is kept for.
        """
        with self._lock:
            draft = self._draft(thread_id, decision.reviewer)
            draft.answers[decision.subject_id] = decision
            draft.assumptions.pop(decision.subject_id, None)

    def put_assumption(self, thread_id: str, person: Person, question_id: str, words: str) -> None:
        """Keep a person's assumption for a question; it replaces their answer to the question.

        Args:
            thread_id: The run.
            person: The person who accepts the assumption.
            question_id: The open question accepted as an assumption.
            words: The assumption in the person's words.
        """
        with self._lock:
            draft = self._draft(thread_id, person)
            draft.assumptions[question_id] = words
            draft.answers.pop(question_id, None)

    def clear(self, thread_id: str) -> None:
        """Drop everyone's pending work on a run once it has been submitted.

        Args:
            thread_id: The run.
        """
        with self._lock:
            for key in [k for k in self._drafts if k[0] == thread_id]:
                del self._drafts[key]
