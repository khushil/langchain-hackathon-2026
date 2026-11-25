"""The closing step: every application and every screening accounted for, or the run stops."""

from __future__ import annotations

import logging
from typing import Any

from context.accounting import account_for_units
from context.errors import AccountingError
from context.reader import entries_of, read_applications, read_screenings
from fsi_common.records import Fact, SourceUnit
from utils.records import FACT_CONTEXT
from workflow.checks import run_check
from workflow.engine_state import EngineState
from workflow.requests import chosen_customers, request_of

LOG = logging.getLogger("workflow.closing")


def all_facts(state: EngineState) -> list[Fact]:
    """Return every content of every fact in the state, validated.

    Args:
        state: The graph state.

    Returns:
        The facts in id order, an id with two contents appearing twice.
    """
    return [
        Fact.model_validate(content, context=FACT_CONTEXT)
        for contents in state.get("facts", {}).values()
        for content in contents
    ]


def held_units(state: EngineState, source_id: str) -> list[SourceUnit]:
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


def close_run(state: EngineState) -> dict[str, Any]:
    """Close the count of applications and screenings, or stop naming what is missing.

    A fresh read of the applications and the lists gives the units each source was read into; the
    state must hold every one of them, and each ends with a fact or a reason. Every application
    must also have its proposal.

    Args:
        state: The graph state after every read and the screening have finished.

    Returns:
        The state update: a unit accounting for each source and the closing counts.

    Raises:
        AccountingError: If a unit is missing, a screening has neither a fact nor a reason, a
            reason is held for a screening that was never read, or an application has no proposal.
    """
    customers = chosen_customers(request_of(state))
    applications = read_applications(customers)
    screenings = read_screenings(customers)
    facts = all_facts(state)
    reasons = state.get("screening_reasons", {})
    stray = sorted(set(reasons) - {u.anchor for u in screenings.units})
    if stray:
        raise AccountingError(
            f"Reasons are held for screening(s) that were never read: {', '.join(stray)}.",
            unexpected=stray,
        )
    proposals = [f for f in facts if f.kind == "proposal"]
    unproposed = [
        u.anchor
        for u in applications.units
        if u.anchor not in {f.subject.anchor for f in proposals}
    ]
    if unproposed:
        raise AccountingError(
            f"Application(s) with no proposal: {', '.join(unproposed)}.", missing=unproposed
        )
    accounting, checks, lines = {}, {}, []
    for read, own_reasons in ((applications, None), (screenings, reasons)):
        result = account_for_units(
            read.source,
            read.units,
            held_units(state, read.source.id),
            facts,
            reasons=own_reasons,
        )
        accounting[read.source.id] = result.accounting.to_json()
        lines.append(result.line)
        detail = result.line
        if result.phantom_anchors:
            detail += f"; facts cite {', '.join(result.phantom_anchors)}, which are not units"
        checks.update(run_check("units-accounted.v1", read.source.id, passed=True, detail=detail))
    entries = len(entries_of())
    settled = sum(1 for f in proposals if f.attributes["settled"])
    failed = [f for f in facts if not f.passed_checks]
    checks.update(
        run_check(
            "screenings-closed.v1",
            screenings.source.id,
            passed=True,
            detail=f"{len(screenings.units)} of {len(applications.units) * entries} screenings "
            f"({len(applications.units)} applications by {entries} list entries) ended as a "
            "fact or on the list of screenings with no likeness",
        )
    )
    checks.update(
        run_check(
            "proposals-made.v1",
            applications.source.id,
            passed=True,
            detail=f"{len(proposals)} of {len(applications.units)} applications have a proposal; "
            f"{settled} settled by the checks and {len(proposals) - settled} sent to a person",
        )
    )
    checks.update(
        run_check(
            "facts-checked.v1",
            applications.source.id,
            passed=True,
            detail=f"{len(facts)} fact records checked, {len(facts) - len(failed)} passed and "
            f"{len(failed)} failed",
        )
    )
    for line in lines:
        LOG.info(line)
    return {"accounting": accounting, "check_results": checks}
