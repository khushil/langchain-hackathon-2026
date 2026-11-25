"""Records and a fake of the engine's run service, for the reviewer's application tests.

The fake implements the names the engine's ``BriefRuns`` has, over records built from the
contract's examples and the starter's section 7, so a page is tested without a graph or a model.
"""

from __future__ import annotations

import asyncio
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from context.tables import read_tables
from fsi_common.examples.data import build_examples
from fsi_common.ids import digest_text
from fsi_common.records import (
    Brief,
    Decision,
    Fact,
    OpenQuestion,
    Source,
    SourceUnit,
    Statement,
    UnitAccounting,
    carry_over,
    record_digest,
)
from review_app.service import NotAwaitingReviewError, RunInProgressError, RunNotFoundError
from utils.records import FACT_CONTEXT
from utils.state import CitedFact, ReviewRequest, ReviewResponse, ReviewStatement

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DOCUMENT = (DATA_DIR / "documents" / "PS26-4.md").read_text(encoding="utf-8")
REVIEWER = {"name": "Dana Whitfield", "role": "Head of Compliance"}
SECTION_7 = (
    (
        "7.1",
        "Firms must submit an initial notification to the FSOA within 4 hours of classifying an "
        "incident as a major incident",
        (
            "Notify the regulator of a major incident",
            "Notify the regulator within 24 hours of detection",
        ),
        "within 4 hours of classifying an incident as a major incident, and in any case no later "
        "than 24 hours after the incident is first detected",
        "obligation",
        "Notify the FSOA of a major incident within 4 hours of classifying it, and no later than "
        "24 hours after first detecting it.",
    ),
    (
        "7.2",
        "Firms must submit an intermediate report within 72 hours of the initial notification",
        ("Send an intermediate report",),
        "within 72 hours of the initial notification",
        "obligation",
        "Send an intermediate report within 72 hours of the initial notification.",
    ),
    (
        "7.3",
        "Firms must submit a final report within 30 business days of the incident being resolved",
        ("Send a final report with a root-cause analysis and the lessons learned",),
        "within 30 business days of the incident being resolved",
        "obligation",
        "Send a final report, with a root-cause analysis and lessons learned, within 30 business "
        "days of resolving the incident.",
    ),
    (
        "7.4",
        "the firm remains responsible for reporting it",
        ("Report an incident caused by a third-party provider",),
        None,
        "obligation",
        "An incident caused by a third-party provider is still the firm's to report.",
    ),
    (
        "7.5",
        "firms may use their existing incident reporting formats",
        ("Use existing incident reporting formats until the template is published",),
        None,
        "permission",
        "Existing incident reporting formats may be used until the FSOA publishes its template.",
    ),
)


def paragraph_text(number: str) -> str:
    """Return a paragraph of the starter's document as the reader splits it."""
    found = re.search(rf"^{re.escape(number)} .+$", DOCUMENT, flags=re.MULTILINE)
    assert found, f"paragraph {number} is not in the document"
    return found.group(0)


def cite(fact: Fact, earlier: Decision | None = None, *, text: str | None = None) -> CitedFact:
    """Return a fact as the reviewer is shown it, with its source paragraph and carry-over."""
    number = fact.subject.anchor.removeprefix("para:")
    return CitedFact(
        fact=fact,
        seen_digest=record_digest(fact),
        unit_text=text or paragraph_text(number),
        carry=carry_over(earlier, fact),
    )


@dataclass
class Review:
    """A review request and the state a finished run would hold beside it."""

    request: ReviewRequest
    state: dict[str, Any]
    facts: dict[str, Fact] = field(default_factory=dict)
    question: OpenQuestion | None = None
    brief: Brief | None = None


def row_texts() -> dict[str, str]:
    """Return the text of each row of the firm and provider tables, by anchor."""
    tables = read_tables("FIRM-001")
    return {u.anchor: tables.unit_text[u.id] for u in tables.units}


def unit_text_of(fact: Fact) -> str:
    """Return the text of the unit a fact quotes: its paragraph, or its table row."""
    scheme, _, rest = fact.subject.anchor.partition(":")
    return paragraph_text(rest) if scheme == "para" else row_texts()[fact.subject.anchor]


def units_of(facts: list[Fact]) -> tuple[dict, dict]:
    """Return the units and unit texts a finished run holds for its facts."""
    units, texts = {}, {}
    for fact in facts:
        text = unit_text_of(fact)
        unit = SourceUnit.build(
            source_id=fact.subject.source_id,
            anchor=fact.subject.anchor,
            text_digest=digest_text(text),
        )
        units[unit.id], texts[unit.id] = unit.to_json(), text
    return units, texts


def accounting_of(facts: list[Fact]) -> dict:
    """Return the unit accounting of each source the facts quote: every unit with facts."""
    anchors: dict[str, list[str]] = {}
    for fact in facts:
        held = anchors.setdefault(fact.subject.source_id, [])
        if fact.subject.anchor not in held:
            held.append(fact.subject.anchor)
    return {
        sid: UnitAccounting.build(
            source_id=sid, units_in=len(found), with_facts=found, without_facts=[]
        ).to_json()
        for sid, found in anchors.items()
    }


def _state(
    sources: list[Source], facts: list[Fact], brief: Brief, question: OpenQuestion | None
) -> dict:
    units, unit_text = units_of(facts)
    return {
        "request": {
            "document_id": "PS26-4",
            "firm_id": "FIRM-001",
            "request": brief.request,
            "sections": ["7"],
        },
        "sources": {s.id: s.to_json() for s in sources},
        "facts": {f.id: [f.to_json()] for f in facts},
        "open_questions": {question.id: question.to_json()} if question else {},
        "draft_brief": brief.to_json(),
        "decisions": {},
        "section_results": {},
        "units": units,
        "unit_text": unit_text,
        "accounting": accounting_of(facts),
    }


def examples_review(*, earlier: dict[str, Decision] | None = None) -> Review:
    """Build the review of the contract's example brief: two statements, one open question.

    Args:
        earlier: Earlier decisions by fact id, which make a fact carried or ask-again.
    """
    ex = build_examples()
    earlier = earlier or {}
    facts = [ex.fact_7_1, ex.fact_9_3]
    statements = [
        ReviewStatement(
            statement_id=s.id,
            heading=s.heading,
            text=s.text,
            facts=[
                cite(next(f for f in facts if f.id == fid), earlier.get(fid)) for fid in s.cites
            ],
        )
        for s in ex.brief.statements
    ]
    request = ReviewRequest(
        brief_id=ex.brief.id,
        brief_digest=ex.brief.content_digest,
        request=ex.brief.request,
        statements=statements,
        open_questions=[ex.question],
    )
    state = _state([ex.document, ex.firms, ex.providers], facts, ex.brief, ex.question)
    return Review(request, state, {f.id: f for f in facts}, ex.question, ex.brief)


def section_seven_review(*, text_suffix: str = "") -> Review:
    """Build a review of section 7 of the starter's document: five statements, one question.

    Args:
        text_suffix: Added to every statement's text, so a second call gives another digest.
    """
    ex = build_examples()
    facts, statements = [], []
    for number, quote, requirement, deadline, kind, text in SECTION_7:
        anchor = f"para:{number}"
        fact = Fact.build(
            context=FACT_CONTEXT,
            kind=kind,
            subject={"source_id": ex.document.id, "anchor": anchor},
            quote=quote,
            attributes={"requirement": list(requirement), "actor": "firm", "deadline": deadline},
            status={"status": "documented"},
            provenance={
                "source_id": ex.document.id,
                "anchor": anchor,
                "extractor": {"name": "section-reader", "version": "0.1.0"},
                "model": "claude-sonnet-5-5",
                "prompt_version": "1",
                "as_of": ex.document.digest,
            },
            checks=[
                {"check": "quote-verbatim.v1", "outcome": "pass", "detail": "found in the unit"},
                *(
                    [{"check": "deadline-verbatim.v1", "outcome": "pass", "detail": "found"}]
                    if deadline
                    else []
                ),
            ],
        )
        facts.append(fact)
        statements.append(
            Statement.build(heading="Incident reporting", cites=[fact.id], text=text + text_suffix)
        )
    question = OpenQuestion.build(
        about={"source_id": ex.firms.id, "anchor": "row:FIRM-001"},
        question="Which of the firm's services count as important business services when an "
        "incident is classified as major?",
        why_unknown="The firm table lists the firm's providers but not its important "
        "business services.",
        impact="Sets which incidents must be notified within 4 hours under paragraph 7.1.",
        ask_role="Head of Operational Resilience",
        reason="missing_data",
        cites=[facts[0].id],
        priority="high",
        state="open",
    )
    brief = Brief.build(
        request="Summarise document PS26-4 for FIRM-001",
        sources=[ex.document.id, ex.firms.id],
        statements=statements,
        open_question_ids=[question.id],
        model="claude-opus-5-5",
        prompt_version="1",
    )
    by_id = {f.id: f for f in facts}
    review_statements = [
        ReviewStatement(
            statement_id=s.id,
            heading=s.heading,
            text=s.text,
            facts=[cite(by_id[i]) for i in s.cites],
        )
        for s in brief.statements
    ]
    request = ReviewRequest(
        brief_id=brief.id,
        brief_digest=brief.content_digest,
        request=brief.request,
        statements=review_statements,
        open_questions=[question],
    )
    return Review(
        request, _state([ex.document, ex.firms], facts, brief, question), by_id, question, brief
    )


@dataclass
class _Run:
    status: str
    request: dict[str, Any]
    review: Review | None = None
    state: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class FakeRuns:
    """The run service's names over in-memory runs; it records what it was asked to do."""

    def __init__(self) -> None:
        self._runs: dict[str, _Run] = {}
        self._lock = threading.Lock()
        self.started: list[dict[str, Any]] = []
        self.submitted: list[tuple[str, ReviewResponse]] = []
        self.calls = 0
        self.on_loop: list[str] = []  # calls made while an event loop ran in the calling thread
        self.raises: dict[str, Exception] = {}  # a failure to raise from a named call
        self.roots: dict[str, Any] = {}  # where each run's graph run was traced, when a test says

    def _note(self, name: str) -> None:
        """Record a call: whether it ran on an event loop, and raise the failure set for it."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            self.on_loop.append(name)
        if name in self.raises:
            raise self.raises[name]

    def add(
        self,
        thread_id: str,
        status: str,
        *,
        review: Review | None = None,
        error: str | None = None,
        request: dict[str, Any] | None = None,
        section_results: dict | None = None,
    ) -> str:
        """Put a run in, in the given status."""
        state = dict(review.state) if review else {"request": request or {}}
        if request:
            state["request"] = request
        if section_results is not None:
            state["section_results"] = section_results
        self._runs[thread_id] = _Run(status, state["request"], review, state, error)
        return thread_id

    def replace_review(self, thread_id: str, review: Review) -> None:
        """Move the brief on, as a rerun would, so its digest changes."""
        run = self._run(thread_id)
        run.review, run.state = review, dict(review.state)

    def _run(self, thread_id: str) -> _Run:
        if thread_id not in self._runs:
            raise RunNotFoundError(f"There is no run {thread_id}.")
        return self._runs[thread_id]

    def start(self, request: dict[str, Any]) -> str:
        """Start a run; refuse a second while one is being written."""
        self._note("start")
        with self._lock:
            if any(r.status == "running" for r in self._runs.values()):
                raise RunInProgressError("A run is still being written.")
            thread_id = f"run-{len(self._runs) + 1}"
            self.started.append(dict(request))
            self._runs[thread_id] = _Run("running", dict(request), None, {"request": dict(request)})
            return thread_id

    def status(self, thread_id: str) -> str:
        """Return the run's status."""
        self._note("status")
        return self._run(thread_id).status

    def review_request(self, thread_id: str) -> ReviewRequest:
        """Return the request the reviewer is shown."""
        self._note("review_request")
        run = self._run(thread_id)
        if run.status != "awaiting_review" or run.review is None:
            raise NotAwaitingReviewError(f"Run {thread_id} is not waiting for a reviewer.")
        self.calls += 1
        return run.review.request

    def submit(self, thread_id: str, response: ReviewResponse) -> str:
        """Take the reviewer's response and finish the run."""
        self._note("submit")
        run = self._run(thread_id)
        if run.status != "awaiting_review" or run.review is None:
            raise NotAwaitingReviewError(f"Run {thread_id} is not waiting for a reviewer.")
        response.check_against(run.review.request)
        self.submitted.append((thread_id, response))
        assert response.sign_off is not None
        run.state["decisions"] = {d.id: d.to_json() for d in response.decisions}
        run.state["sign_off"] = response.sign_off.to_json()
        run.status = response.sign_off.outcome
        return run.status

    def root_run(self, thread_id: str) -> Any:
        """Return where the run was traced, when a test has given it a place."""
        self._note("root_run")
        self._run(thread_id)
        return self.roots.get(thread_id)

    def result(self, thread_id: str) -> dict[str, Any]:
        """Return the run's state as it stands."""
        self._note("result")
        return self._run(thread_id).state

    def error(self, thread_id: str) -> str | None:
        """Return the failure in words."""
        self._note("error")
        return self._run(thread_id).error

    def list_runs(self) -> list[str]:
        """Return the run ids, newest first."""
        self._note("list_runs")
        return list(reversed(self._runs))
