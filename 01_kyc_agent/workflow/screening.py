"""The screen step: every application against every list entry, then each application's proposal."""

from __future__ import annotations

from typing import Any

from context.errors import AccountingError
from context.extraction import Applicant, ApplicantFacts
from context.proposals import assess_application
from context.reader import entries_of, read_applications, read_screenings, screening_anchor
from context.screening import PairResult, screen_pair
from fsi_common.records import OpenQuestion
from utils.kyc_state import fact_writes
from utils.records import APPLICANT_KINDS
from workflow.checks import run_check
from workflow.closing import all_facts
from workflow.engine_state import EngineState


def screen_applicant(
    applicant: Applicant, units: dict[str, Any], texts: dict[str, str], source: Any
) -> list[PairResult]:
    """Set one application against every list entry.

    Args:
        applicant: What the reading gave.
        units: The screening units by anchor.
        texts: The screening units' texts by unit id.
        source: The screenings source.

    Returns:
        One result for each list entry, in list order.

    Raises:
        AccountingError: If a screening returns no result, or one with neither a fact nor a
            reason; the screening is named.
    """
    results = []
    for entry in entries_of():
        anchor = screening_anchor(applicant.customer_id, entry.anchor_part)
        unit = units[anchor]
        result = screen_pair(applicant, entry, source=source, unit=unit, unit_text=texts[unit.id])
        if result is None or (result.fact is None and not result.reason):
            raise AccountingError(
                f"The screening {anchor} ended with neither a fact nor a reason.", missing=[anchor]
            )
        results.append(result)
    return results


def screen_and_propose(state: EngineState) -> dict[str, Any]:
    """Screen every application against every entry, and propose for each application.

    Args:
        state: The graph state, whose applicants every read step has written.

    Returns:
        The state update: the screening and proposal facts, the questions with their two readings,
        the reason each screening with no fact has none, and the counts for each application.

    Raises:
        AccountingError: If a screening ends with neither a fact nor a reason.
    """
    customers = sorted(state["applicants"])
    applications = read_applications(customers)
    screenings = read_screenings(customers)
    by_row = {u.anchor: u for u in applications.units}
    by_pair = {u.anchor: u for u in screenings.units}
    entries = entries_of()
    held_facts = all_facts(state)
    held_questions = [
        OpenQuestion.model_validate(q) for q in state.get("open_questions", {}).values()
    ]
    facts, questions, readings, reasons, checks = [], {}, {}, {}, {}
    for customer in customers:
        applicant = Applicant.from_json(state["applicants"][customer])
        pairs = screen_applicant(applicant, by_pair, screenings.unit_text, screenings.source)
        unit = by_row[f"row:{customer}"]
        about = [
            f for f in held_facts if f.subject.anchor == unit.anchor and f.kind in APPLICANT_KINDS
        ]
        asked = [q for q in held_questions if q.about.anchor == unit.anchor]
        outcome = assess_application(
            ApplicantFacts(applicant=applicant, facts=about, questions=asked),
            pairs,
            source=applications.source,
            unit=unit,
            text=applications.unit_text[unit.id],
            entries=entries,
        )
        facts += outcome.facts
        questions.update({q.id: q.to_json() for q in outcome.questions})
        readings.update({i: r.model_dump(mode="json") for i, r in outcome.readings.items()})
        reasons.update(outcome.reasons)
        screened = [p for p in pairs if p.fact is not None]
        checks.update(
            run_check(
                "screened.v1",
                customer,
                passed=True,
                detail=f"{len(pairs)} of {len(entries)} screenings of {customer} ended: "
                f"{len(screened)} as facts, {len(outcome.reasons)} with a reason and no fact",
            )
        )
    return {
        "facts": fact_writes(facts),
        "open_questions": questions,
        "readings": readings,
        "screening_reasons": reasons,
        "check_results": checks,
    }
