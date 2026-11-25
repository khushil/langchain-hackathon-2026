"""A run's state read into the records the pages draw: facts, questions, accounting and names."""

from __future__ import annotations

from dataclasses import dataclass

from context.reader import ListEntry, entries_of
from fsi_common.records import Fact, OpenQuestion, UnitAccounting
from utils.kyc_state import KycState
from utils.records import FACT_CONTEXT, customer_of_anchor


@dataclass(frozen=True)
class RunData:
    """One run's records, parsed once for a page."""

    customers: tuple[str, ...]
    entries: tuple[ListEntry, ...]
    facts: dict[str, Fact]
    questions: dict[str, OpenQuestion]
    names: dict[str, str | None]
    reasons: dict[str, str]
    texts: dict[str, str]
    screenings: UnitAccounting | None
    applications: UnitAccounting | None

    def facts_of(self, customer_id: str, *kinds: str) -> list[Fact]:
        """Return the facts about one application, of the kinds named when any are, in id order."""
        return [
            f
            for f in self.facts.values()
            if customer_of_anchor(f.subject.anchor) == customer_id
            and (not kinds or f.kind in kinds)
        ]

    def questions_of(self, customer_id: str) -> list[OpenQuestion]:
        """Return the open questions about one application."""
        return [
            q for q in self.questions.values() if customer_of_anchor(q.about.anchor) == customer_id
        ]


def read_run_data(state: KycState) -> RunData:
    """Read a run's state into records.

    Args:
        state: The run's state as ``KycRuns.result`` gives it.

    Returns:
        The parsed records. A fact id that holds two contents shows its first.
    """
    facts = {
        fid: Fact.model_validate(contents[0], context=FACT_CONTEXT)
        for fid, contents in state.get("facts", {}).items()
    }
    sources = {sid: s["key"] for sid, s in state.get("sources", {}).items()}
    accounting = {
        sources[sid]: UnitAccounting.model_validate(a)
        for sid, a in state.get("accounting", {}).items()
        if sid in sources
    }
    applicants = state.get("applicants", {})
    units = {u["id"]: u["anchor"] for u in state.get("units", {}).values()}
    texts = {
        units[uid].partition(":")[2]: text
        for uid, text in state.get("unit_text", {}).items()
        if uid in units and units[uid].startswith("row:")
    }
    customers = tuple(sorted(applicants) or sorted(texts))
    return RunData(
        customers=customers,
        entries=entries_of(),
        facts=facts,
        questions={
            qid: OpenQuestion.model_validate(q)
            for qid, q in state.get("open_questions", {}).items()
        },
        names={c: applicants.get(c, {}).get("name") for c in customers},
        reasons=dict(state.get("screening_reasons", {})),
        texts=texts,
        screenings=accounting.get("screenings"),
        applications=accounting.get("applications"),
    )
