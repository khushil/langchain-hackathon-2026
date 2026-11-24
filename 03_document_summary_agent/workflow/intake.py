"""The first step: read the document and the firm's tables, and send each section on."""

from __future__ import annotations

from typing import Any

from langgraph.types import Send

from context.reader import read_document
from context.tables import read_tables
from utils.records import PARAGRAPH_SCHEME
from utils.state import fact_writes
from workflow.checks import run_check
from workflow.engine_state import EngineState
from workflow.requests import request_of, selected_sections


def read_sources(state: EngineState) -> dict[str, Any]:
    """Read the document and the firm's tables into sources, units and table facts.

    Only the paragraphs of the sections the request selects become units of the run, so the
    accounting that follows states its counts for those sections.

    Args:
        state: The graph state, holding the request.

    Returns:
        The state update: sources, units, unit texts, the tables' facts and the counts read.

    Raises:
        DocumentNotFoundError: If the document is not in the library.
        FirmNotFoundError: If the firm is not in the firm table.
        UnknownSectionError: If the request names a section the document does not have.
    """
    request = request_of(state)
    document = read_document(request["document_id"])
    tables = read_tables(request["firm_id"])
    chosen = selected_sections(document, request)
    chosen_anchors = {p.anchor for section in chosen for p in section.paragraphs}
    units = [u for u in document.units if u.anchor in chosen_anchors] + list(tables.units)
    unit_text = {u.id: document.unit_text[u.id] for u in units if u.id in document.unit_text}
    unit_text.update(tables.unit_text)
    sources = [document.source, *tables.sources]
    checks = {
        **run_check(
            "sections-selected.v1",
            document.source.id,
            passed=True,
            detail=f"{len(chosen)} of {len(document.sections)} sections selected "
            f"({', '.join(s.number for s in chosen)})",
        ),
        **run_check(
            "units-read.v1",
            document.source.id,
            passed=True,
            detail=f"{len(chosen_anchors)} of {len(document.units)} paragraphs are in the "
            "sections selected and read as units",
        ),
    }
    for source in tables.sources:
        rows = [u for u in tables.units if u.source_id == source.id]
        checks.update(
            run_check(
                "units-read.v1",
                source.id,
                passed=True,
                detail=f"{len(rows)} of {len(rows)} rows of {source.key} read as units",
            )
        )
    return {
        "sources": {s.id: s.to_json() for s in sources},
        "units": {u.id: u.to_json() for u in units},
        "unit_text": unit_text,
        "facts": fact_writes(tables.facts),
        "check_results": checks,
    }


def send_sections(state: EngineState) -> list[Send]:
    """Send one section step for each section the run reads, in section order.

    Args:
        state: The graph state, whose units name the sections selected.

    Returns:
        One ``Send`` to the section step for each section number.
    """
    request = request_of(state)
    numbers = sorted(
        {
            anchor.partition(":")[2].partition(".")[0]
            for unit in state["units"].values()
            if (anchor := unit["anchor"]).startswith(f"{PARAGRAPH_SCHEME}:")
        },
        key=lambda number: (len(number), number),
    )
    return [Send("section", {"request": dict(request), "section": number}) for number in numbers]
