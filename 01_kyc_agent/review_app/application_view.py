"""One application as its page shows it: its words, the details read, screenings and proposal."""

from __future__ import annotations

import re
from dataclasses import dataclass

from context.readings import Readings
from fsi_common.records import Fact, OpenQuestion
from review_app.run_data import RunData
from review_app.wording import LISTS, check_label, kind_label, proposal_words
from utils.records import APPLICANT_KINDS

DETAIL_ORDER = {kind: n for n, kind in enumerate(APPLICANT_KINDS)}


@dataclass(frozen=True)
class Segment:
    """A run of the application's text, marked when it is words a fact quotes."""

    text: str
    marked: bool


@dataclass(frozen=True)
class DetailRow:
    """One detail read from the application, with its quote and whether its checks passed."""

    label: str
    value: str
    quote: str
    passed: bool
    failures: tuple[str, ...]


@dataclass(frozen=True)
class ScreeningRow:
    """One screening kept as a fact."""

    fact: Fact
    entry: str
    list_label: str
    detail: str
    score: str
    dates: str
    how: str
    why: str | None
    question_id: str | None


@dataclass(frozen=True)
class QuestionView:
    """One open question with the two readings beside each other."""

    question: OpenQuestion
    readings: Readings | None
    resting: tuple[str, ...]


@dataclass(frozen=True)
class ApplicationView:
    """Everything one application's page draws, read from the run's records."""

    customer_id: str
    name: str | None
    segments: tuple[Segment, ...]
    details: tuple[DetailRow, ...]
    screenings: tuple[ScreeningRow, ...]
    no_likeness: int
    not_screened: int
    proposal: Fact
    questions: tuple[QuestionView, ...]

    @property
    def screenings_total(self) -> int:
        """The screenings of this application: facts, no likeness and not run."""
        return len(self.screenings) + self.no_likeness + self.not_screened

    @property
    def heading(self) -> str:
        """The application named for a title."""
        return f"{self.name} ({self.customer_id})" if self.name else self.customer_id

    @property
    def sentence(self) -> str:
        """The proposal as one sentence."""
        attributes = self.proposal.attributes
        head = f"{self.heading}: proposed {proposal_words(self.proposal).lower()}."
        if attributes["settled"]:
            return f"{head} Settled by the checks."
        asked = len(self.questions)
        noun = "question" if asked == 1 else "questions"
        return f"{head} The checks did not settle it: {asked} {noun} for a person."


def mark_quotes(text: str, quotes: list[str]) -> tuple[Segment, ...]:
    """Split an application around the first place each quote occurs word for word.

    White space may differ between the text and a quote; the words may not. A quote that is not
    in the text, or lies inside one already marked, marks nothing.

    Args:
        text: The application.
        quotes: The quotes of the facts that passed their checks.

    Returns:
        The segments in order, with the quoted words marked.
    """
    spans: list[tuple[int, int]] = []
    for quote in quotes:
        words = quote.split()
        found = re.search(r"\s+".join(re.escape(w) for w in words), text) if words else None
        if found and not any(a < found.end() and found.start() < b for a, b in spans):
            spans.append(found.span())
    segments, at = [], 0
    for start, end in sorted(spans):
        if start > at:
            segments.append(Segment(text[at:start], False))
        segments.append(Segment(text[start:end], True))
        at = end
    if at < len(text):
        segments.append(Segment(text[at:], False))
    return tuple(segments)


def _detail(fact: Fact) -> DetailRow:
    value = fact.attributes.get("value") or fact.attributes.get("amount")
    if fact.kind == "relation":
        parts = [
            fact.attributes["relation"],
            fact.attributes["related_name"],
            fact.attributes["related_office"],
        ]
        value = ", ".join(str(p) for p in parts if p)
    failures = tuple(c.detail for c in fact.checks if c.outcome == "fail")
    return DetailRow(kind_label(fact.kind), str(value), fact.quote, not failures, failures)


def _dates(attributes: dict) -> str:
    agrees = attributes["dob_agrees"]
    if agrees is None:
        return "Cannot be compared"
    return "Agree" if agrees else "Differ"


def _screening(fact: Fact, questions: dict[str, OpenQuestion]) -> ScreeningRow:
    a = fact.attributes
    asked = next(
        (q for q in questions.values() if fact.id in q.cites and q.about == fact.subject), None
    )
    return ScreeningRow(
        fact=fact,
        entry=a["entry_name"],
        list_label=LISTS[a["list"]],
        detail=a["entry_detail"],
        score=a["name_score"],
        dates=_dates(a),
        how="Settled by the checks" if a["outcome"] == "settled" else "Needs a person",
        why=a["why_unsettled"],
        question_id=asked.id if asked else None,
    )


def build_application(data: RunData, readings: dict, customer_id: str) -> ApplicationView | None:
    """Read one application's records into what its page draws.

    Args:
        data: The run's records.
        readings: The state's readings of the questions, by question id, as JSON.
        customer_id: The application.

    Returns:
        The view, or None when the run holds no application by that id.
    """
    if customer_id not in data.customers:
        return None
    mine = data.facts_of(customer_id)
    details = sorted(
        (f for f in mine if f.kind in APPLICANT_KINDS), key=lambda f: DETAIL_ORDER[f.kind]
    )
    questions = {q.id: q for q in data.questions_of(customer_id)}
    shown = tuple(
        QuestionView(
            q,
            Readings.model_validate(readings[q.id]) if q.id in readings else None,
            tuple(c for c in q.cites if c in data.facts),
        )
        for q in questions.values()
    )
    reasons = [r for a, r in data.reasons.items() if a.startswith(f"pair:{customer_id}/")]
    proposal = next(f for f in mine if f.kind == "proposal")
    return ApplicationView(
        customer_id=customer_id,
        name=data.names.get(customer_id),
        segments=mark_quotes(
            data.texts[customer_id], [f.quote for f in details if f.passed_checks]
        ),
        details=tuple(_detail(f) for f in details),
        screenings=tuple(_screening(f, questions) for f in mine if f.kind == "screening"),
        no_likeness=sum(r.startswith("No likeness") for r in reasons),
        not_screened=sum(r.startswith("Not screened") for r in reasons),
        proposal=proposal,
        questions=shown,
    )


def failed_check_words(fact: Fact) -> list[str]:
    """Name each failed check of a fact in words, with what it found."""
    return [f"{check_label(c)}: {c.detail}" for c in fact.checks if c.outcome == "fail"]
