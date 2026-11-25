"""The closing step: every unit accounted for, every transaction assessed or asked about."""

from __future__ import annotations

import logging
from typing import Any

from context.accounting import NO_ASSESSMENT_REASON, account_for_units
from context.errors import AccountingError
from context.questions import question_for_failed, question_for_missing
from fsi_common.records import Fact, SourceUnit
from utils.records import FACT_CONTEXT, transaction_anchor
from workflow.checks import run_check
from workflow.intake import stream_of
from workflow.state import MonitorState

LOG = logging.getLogger("workflow.closing")


def all_facts(state: MonitorState) -> list[Fact]:
    """Return every fact in the state, validated.

    Args:
        state: The graph state.

    Returns:
        The facts in id order.
    """
    return [
        Fact.model_validate(content, context=FACT_CONTEXT)
        for content in state.get("facts", {}).values()
    ]


def held_units(state: MonitorState, source_id: str) -> list[SourceUnit]:
    """Return the units of one source that the state holds.

    Args:
        state: The graph state.
        source_id: The source's id.

    Returns:
        The units, validated.
    """
    return [
        SourceUnit.model_validate(unit)
        for unit in state.get("units", {}).values()
        if unit["source_id"] == source_id
    ]


def close_run(state: MonitorState) -> dict[str, Any]:
    """Close the count of units and of assessments, or stop naming what is missing.

    A fresh read of the stream gives the units each source was read into; the state must hold
    every one of them, and the assessing step must have returned something for every
    transaction. Each transaction ends with an assessment fact or on the list of units with no
    fact, with its reason; one with no fact, and one whose fact failed a check, becomes an open
    question for the reviewer, so none is decided by default.

    Args:
        state: The graph state after the assessing step.

    Returns:
        The state update: a unit accounting for each source, the open questions and the counts.

    Raises:
        AccountingError: If a unit is missing from the state or the assessing step returned
            nothing for a transaction.
    """
    stream = stream_of(state)
    transactions, profiles = stream.sources
    raw = state.get("raw_assessments", {})
    unreturned = [
        r["transaction_id"] for r in stream.transactions if r["transaction_id"] not in raw
    ]
    if unreturned:
        raise AccountingError(
            f"The assessing step returned nothing for {', '.join(unreturned)}.",
            missing=[transaction_anchor(t) for t in unreturned],
        )
    facts = all_facts(state)
    by_anchor = {f.subject.anchor: f for f in facts if f.kind == "transaction_assessment"}
    expected = {
        transactions.id: [u for u in stream.units if u.source_id == transactions.id],
        profiles.id: [u for u in stream.units if u.source_id == profiles.id],
    }
    questions, no_fact = {}, {}
    failed = 0
    for row in stream.transactions:
        anchor = transaction_anchor(row["transaction_id"])
        unit = stream.unit_of[anchor]
        fact = by_anchor.get(anchor)
        if fact is None:
            question = question_for_missing(unit, row)
            no_fact[anchor] = NO_ASSESSMENT_REASON
        elif fact.passed_checks:
            continue
        else:
            question = question_for_failed(fact, unit, row)
            failed += 1
        questions[question.id] = question.to_json()
    accounting, checks, lines = {}, {}, []
    for source in stream.sources:
        result = account_for_units(
            source,
            expected[source.id],
            held_units(state, source.id),
            facts,
            reasons=no_fact if source.id == transactions.id else None,
        )
        accounting[source.id] = result.accounting.to_json()
        lines.append(result.line)
        detail = result.line
        if result.phantom_anchors:
            detail += f"; facts cite {', '.join(result.phantom_anchors)}, which are not units"
        checks.update(run_check("units-accounted.v1", source.id, passed=True, detail=detail))
    total, missing = len(stream.transactions), len(no_fact)
    passing = total - missing - failed
    checks.update(
        run_check(
            "assessments-recorded.v1",
            transactions.id,
            passed=True,
            detail=f"{passing} of {total} transactions have an assessment that passed every "
            f"check; {failed} failed a check and {missing} have none",
        )
    )
    for line in lines:
        LOG.info(line)
    return {"accounting": accounting, "check_results": checks, "open_questions": questions}
