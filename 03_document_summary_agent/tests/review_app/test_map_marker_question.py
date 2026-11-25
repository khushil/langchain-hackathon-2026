"""The picture shows "Open question" for a paragraph the marker check asked the reviewer about."""

from __future__ import annotations

from context.accounting import marked_no_fact_reason
from context.marker_check import (
    marked_without_obligation,
    unconfirmed_questions,
    unmarked_obligation_questions,
)
from context.reader import paragraph_unit, read_document
from fsi_common.records import CheckResult, Fact, UnitAccounting
from review_app.paragraph_map import build_map, paragraph_panel, plain_reason
from utils.records import FACT_CONTEXT

DOCUMENT = read_document("PS26-4")
SOURCE = DOCUMENT.source
SECTION9 = DOCUMENT.section("9")


def _fact(number: str, outcome: str = "pass") -> Fact:
    anchor = f"para:{number}"
    return Fact.build(
        context=FACT_CONTEXT,
        kind="obligation",
        subject={"source_id": SOURCE.id, "anchor": anchor},
        quote=DOCUMENT.paragraph(anchor).text[:20],
        attributes={"requirement": ["a duty"], "deadline": None},
        status={"status": "documented"},
        provenance={
            "source_id": SOURCE.id,
            "anchor": anchor,
            "extractor": {"name": "x", "version": "1"},
            "as_of": SOURCE.digest,
        },
        checks=[CheckResult(check="quote-verbatim.v1", outcome=outcome, detail="d")],
    )


def _state(facts: list[Fact], *, without: dict[str, str]) -> dict:
    """The state of a run of section 9 with these facts, the paragraphs without a fact and why."""
    questions = [
        *unconfirmed_questions(
            marked_without_obligation(SECTION9.paragraphs, facts), source=SOURCE
        ),
        *unmarked_obligation_questions(SECTION9.paragraphs, facts, source=SOURCE),
    ]
    units = [paragraph_unit(SOURCE, p) for p in SECTION9.paragraphs]
    with_facts = [u.anchor for u in units if u.anchor not in without]
    accounting = UnitAccounting.build(
        source_id=SOURCE.id,
        units_in=len(units),
        with_facts=with_facts,
        without_facts=[{"anchor": a, "reason": r} for a, r in without.items()],
    )
    return {
        "sources": {SOURCE.id: SOURCE.to_json()},
        "units": {u.id: u.to_json() for u in units},
        "unit_text": {paragraph_unit(SOURCE, p).id: p.text for p in SECTION9.paragraphs},
        "accounting": {SOURCE.id: accounting.to_json()},
        "facts": {f.id: [f.to_json()] for f in facts},
        "open_questions": {q.id: q.to_json() for q in questions},
    }


def _cells(state: dict) -> dict:
    found = build_map(
        state,
        sections=["9"],
        titles={"9": "Transitional provisions"},
        href_for=lambda anchor, ids: f"#{anchor}",
    )
    assert found is not None
    return {cell.number: cell for section in found.sections for cell in section.cells}


def test_a_marked_paragraph_with_no_fact_and_a_question_shows_open_question():
    reason = marked_no_fact_reason("must")
    cells = _cells(
        _state(
            [_fact("9.1")],
            without={"para:9.2": "none", "para:9.3": reason, "para:9.4": "none"},
        )
    )
    assert cells["9.3"].finding.word == "Open question"
    assert cells["9.3"].finding.kind == "question"
    assert '"must"' in cells["9.3"].finding.detail
    assert cells["9.2"].finding.word == "No fact" and cells["9.4"].finding.word == "No fact"


def test_an_obligation_fact_on_an_unmarked_paragraph_shows_open_question_too():
    cells = _cells(
        _state(
            [_fact("9.1"), _fact("9.3")],
            without={"para:9.2": "none", "para:9.4": "none"},
        )
    )
    assert cells["9.1"].finding.word == "Open question"
    assert cells["9.1"].finding.detail.startswith("Open question; Obligation")
    assert cells["9.3"].finding.word == "Obligation"


def test_the_count_beside_the_picture_still_closes_with_a_paragraph_that_is_a_question():
    state = _state([_fact("9.1")], without={"para:9.2": "n", "para:9.3": "m", "para:9.4": "n"})
    found = build_map(state, sections=["9"], titles={}, href_for=lambda a, i: "#")
    assert found.count == "4 of 4 paragraphs of section 9 accounted for"


def test_the_paragraph_opened_from_the_picture_says_in_words_which_marker_was_found():
    reason = marked_no_fact_reason("must")
    state = _state([_fact("9.1")], without={"para:9.2": "n", "para:9.3": reason, "para:9.4": "n"})
    panel = paragraph_panel(state, "9.3")
    assert panel is not None and panel.reason == plain_reason(reason)
    assert panel.reason == (
        'The paragraph contains "must", which can mark an obligation, but no obligation was '
        "recorded from it. A question about it is open."
    )
    assert "second read" not in panel.reason and "reviewer" not in panel.reason
