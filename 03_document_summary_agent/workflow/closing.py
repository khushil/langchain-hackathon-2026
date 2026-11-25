"""The closing step: every unit accounted for, every section back, every fact's checks counted."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from context.accounting import account_for_units, marked_no_fact_reason, no_fact_reason
from context.errors import AccountingError
from context.marker_check import MARKED_REASON, marked_without_obligation
from context.markers import marker_in
from context.reader import Paragraph, read_document
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


def marked_reasons(
    state: EngineState, paragraphs: Sequence[Paragraph], *, facts: Sequence[Fact]
) -> dict[str, str]:
    """Give each paragraph with a marker and no passing obligation fact its reason, or stop.

    A paragraph that holds an obligation marker and has no obligation fact that passed its checks
    must be the subject of an open question of the reason a marked paragraph is asked with;
    closing it with the plain reason for a paragraph with no fact would be the drop the
    accounting exists to catch.

    Args:
        state: The graph state, whose open questions are looked at.
        paragraphs: The paragraphs of the sections the run read.
        facts: Every fact of the run.

    Returns:
        The reason for each such paragraph's anchor, naming its marker.

    Raises:
        AccountingError: If such a paragraph has no open question about it; each is named with
            its marker.
    """
    asked = {
        q["about"]["anchor"]
        for q in state.get("open_questions", {}).values()
        if q["reason"] == MARKED_REASON
    }
    marked = marked_without_obligation(paragraphs, facts)
    unasked = [m for m in marked if m.paragraph.anchor not in asked]
    if unasked:
        shown = ", ".join(f'{m.paragraph.number} ("{m.marker}")' for m in unasked)
        raise AccountingError(
            f"Paragraph(s) {shown} hold an obligation marker, have no obligation fact that passed "
            "its checks and are not an open question, so they cannot be closed as holding none."
        )
    return {m.paragraph.anchor: marked_no_fact_reason(m.marker) for m in marked}


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
    paragraphs = [p for s in chosen for p in s.paragraphs]
    reasons = marked_reasons(state, paragraphs, facts=facts)
    marked_total = sum(1 for p in paragraphs if marker_in(p.text))
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
            reasons=reasons if source.id == document.source.id else None,
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
            "markers-closed.v1",
            document.source.id,
            passed=True,
            detail=f"{len(reasons)} of {marked_total} paragraphs that hold an obligation marker "
            f"have no obligation fact that passed its checks and are open questions; "
            f"{marked_total - len(reasons)} "
            "have one",
        )
    )
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
