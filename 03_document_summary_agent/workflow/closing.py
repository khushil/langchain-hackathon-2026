"""The closing step: every unit accounted for, every section back, every fact's checks counted."""

from __future__ import annotations

import logging
from typing import Any

from context.accounting import account_for_units, no_fact_reason
from context.errors import AccountingError
from context.reader import read_document
from context.tables import read_tables

from fsi_common.records import Extractor, Fact, SourceUnit
from utils.records import FACT_CONTEXT
from utils.state import variant_disagreements
from workflow.checks import run_check
from workflow.engine_state import EngineState
from workflow.requests import request_of, selected_sections

LOG = logging.getLogger("workflow.closing")
VARIANT_FINDER = Extractor(name="fact-variants", version="0.1.0")
"""The comparison that finds one fact id read two ways."""


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
    """Close the count of units, sections and checked facts, or stop naming what is missing.

    A fresh read of the document and the tables gives the units each source was read into; the
    state must hold every one of them. Each unit ends with facts or with a recorded reason, and
    each section the run selected must have returned its result.

    Args:
        state: The graph state after every section step has finished.

    Returns:
        The state update: a unit accounting for each source, the facts' disagreements and the
        closing counts.

    Raises:
        AccountingError: If a unit is missing, or a selected section has no result.
    """
    request = request_of(state)
    document = read_document(request["document_id"])
    tables = read_tables(request["firm_id"])
    chosen = selected_sections(document, request)
    chosen_anchors = {p.anchor for section in chosen for p in section.paragraphs}
    facts = all_facts(state)
    results = state.get("section_results", {})
    missing_sections = [s.number for s in chosen if s.number not in results]
    if missing_sections:
        raise AccountingError(
            f"Section(s) {', '.join(missing_sections)} were selected and returned no result."
        )
    listed = {fact_id for result in results.values() for fact_id in result["fact_ids"]}
    unheld = sorted(listed - set(state.get("facts", {})))
    if unheld:
        raise AccountingError(
            f"The section results list fact(s) the state does not hold: {', '.join(unheld)}."
        )
    expected = {
        document.source.id: [u for u in document.units if u.anchor in chosen_anchors],
        **{s.id: [u for u in tables.units if u.source_id == s.id] for s in tables.sources},
    }
    accounting, checks, lines = {}, {}, []
    for source in [document.source, *tables.sources]:
        result = account_for_units(
            source,
            expected[source.id],
            held_units(state, source.id),
            facts,
            reason=no_fact_reason(source),
        )
        accounting[source.id] = result.accounting.to_json()
        lines.append(result.line)
        detail = result.line
        if result.phantom_anchors:
            detail += f"; facts cite {', '.join(result.phantom_anchors)}, which are not units"
        checks.update(run_check("units-accounted.v1", source.id, passed=True, detail=detail))
    failed = [f for f in facts if not f.passed_checks]
    checks.update(
        run_check(
            "sections-returned.v1",
            document.source.id,
            passed=True,
            detail=f"{len(chosen)} of {len(chosen)} selected sections returned a result",
        )
    )
    checks.update(
        run_check(
            "facts-checked.v1",
            document.source.id,
            passed=True,
            detail=f"{len(listed)} of {len(listed)} facts listed by the section results are held; "
            f"{len(facts)} fact records checked, {len(facts) - len(failed)} passed and "
            f"{len(failed)} failed",
        )
    )
    for line in lines:
        LOG.info(line)
    disagreements = variant_disagreements(state.get("facts", {}), found_by=VARIANT_FINDER)
    return {
        "accounting": accounting,
        "check_results": checks,
        "disagreements": {d.id: d.to_json() for d in disagreements},
    }
