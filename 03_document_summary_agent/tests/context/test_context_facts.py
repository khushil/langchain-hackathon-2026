"""Tests of turning a section's result into checked facts and open questions."""

import pytest

from context.errors import SectionReadError
from context.facts import SECTION_READER, read_section, requirement_mismatches
from context.reader import read_document
from fsi_common.records import Fact
from sub_agent import Obligation, SectionSummary
from utils.records import FACT_CONTEXT, records_to_section_summary

DOCUMENT = read_document("PS26-4")
SECTION7 = DOCUMENT.section("7")


def _summary(*obligations: Obligation, number: str = "7") -> SectionSummary:
    return SectionSummary(
        number=number,
        title="Incident reporting",
        summary="Firms report major incidents quickly.",
        obligations=list(obligations),
    )


def _clean() -> Obligation:
    return Obligation(
        requirement="Notify the FSOA of a major incident",
        paragraph="7.1",
        deadline="within 4 hours of classifying an incident as a major incident",
        evidence="Firms must submit an initial notification to the FSOA within 4 hours",
    )


def _read(summary: SectionSummary):
    return read_section(
        summary,
        section=SECTION7,
        source=DOCUMENT.source,
        model="claude-sonnet-5-5",
        prompt_version="1",
    )


def test_read_section_turns_a_clean_obligation_into_a_passing_cited_fact():
    read = _read(_summary(_clean()))
    (fact,) = read.facts.values()
    assert fact.kind == "obligation"
    assert fact.subject.anchor == "para:7.1"
    assert fact.provenance.as_of == DOCUMENT.source.digest
    assert fact.provenance.extractor == SECTION_READER
    assert fact.provenance.model == "claude-sonnet-5-5"
    assert [(c.check, c.outcome) for c in fact.checks] == [
        ("quote-verbatim.v1", "pass"),
        ("deadline-verbatim.v1", "pass"),
    ]
    assert fact.passed_checks
    assert read.questions == []
    assert read.result.fact_ids == [fact.id]
    assert read.result.number == "7"


def test_read_section_keeps_a_paraphrased_quote_with_its_failed_check():
    paraphrase = _clean().model_copy(
        update={"evidence": "Firms have to send a first notice to the FSOA inside four hours"}
    )
    (fact,) = _read(_summary(paraphrase)).facts.values()
    assert not fact.passed_checks
    failed = [c for c in fact.checks if c.outcome == "fail"]
    assert [c.check for c in failed] == ["quote-verbatim.v1"]
    assert "not found word for word" in failed[0].detail


def test_read_section_keeps_a_converted_deadline_with_its_failed_check():
    converted = _clean().model_copy(update={"deadline": "4h"})
    (fact,) = _read(_summary(converted)).facts.values()
    assert not fact.passed_checks
    assert [(c.check, c.outcome) for c in fact.checks] == [
        ("quote-verbatim.v1", "pass"),
        ("deadline-verbatim.v1", "fail"),
    ]


def test_read_section_makes_no_fact_for_a_paragraph_that_does_not_exist_and_asks_instead():
    invented = _clean().model_copy(update={"paragraph": "7.9"})
    read = _read(_summary(invented))
    (question,) = read.questions
    assert read.facts == {}
    assert read.result.fact_ids == []
    assert question.reason == "unresolved_reference"
    assert question.about.anchor == "para:7.9"
    assert question.state == "open"
    assert "7.9" in question.question
    assert "section 7" in question.question
    assert invented.evidence in question.question
    section_anchors = {p.anchor for p in SECTION7.paragraphs}
    held = {u.id for u in DOCUMENT.units if u.anchor in section_anchors}
    assert question.cites and set(question.cites) == held


def test_read_section_treats_a_paragraph_of_another_section_as_not_found_in_this_one():
    elsewhere = _clean().model_copy(update={"paragraph": "9.4"})
    read = _read(_summary(elsewhere))
    (question,) = read.questions
    assert question.about.anchor == "para:9.4"
    assert read.facts == {}


def test_read_section_makes_one_question_for_two_obligations_citing_one_missing_paragraph():
    first = _clean().model_copy(update={"paragraph": "7.9"})
    second = first.model_copy(update={"requirement": "Another duty", "evidence": "Firms must"})
    read = _read(_summary(first, second))
    (question,) = read.questions
    assert first.evidence in question.question and "Firms must" in question.question


def test_read_section_keeps_a_real_obligation_beside_one_on_a_missing_paragraph():
    invented = _clean().model_copy(update={"paragraph": "7.9"})
    read = _read(_summary(_clean(), invented))
    (fact,) = read.facts.values()
    assert fact.subject.anchor == "para:7.1"
    assert read.result.fact_ids == [fact.id]
    assert len(read.questions) == 1
    assert read.count_check.outcome == "pass"
    assert "1 cite a paragraph" in read.count_check.detail


def test_read_section_keeps_the_order_and_repeats_of_the_obligations():
    other = Obligation(
        requirement="Send an intermediate report",
        paragraph="7.2",
        deadline="within 72 hours of the initial notification",
        evidence="Firms must submit an intermediate report within 72 hours",
    )
    summary = _summary(_clean(), other, _clean())
    read = _read(summary)
    assert len(read.result.fact_ids) == 3
    assert read.result.fact_ids[0] == read.result.fact_ids[2]
    assert len(read.facts) == 2
    assert records_to_section_summary(read.result, read.facts) == summary


def test_read_section_with_no_obligations_has_no_facts_and_no_question():
    read = _read(_summary())
    assert read.facts == {} and read.questions == [] and read.result.fact_ids == []


def test_read_section_uses_the_section_as_read_when_the_model_mislabels_it():
    read = _read(_summary(_clean(), number="8"))
    assert read.result.number == "7"
    assert read.result.title == "Incident reporting"
    assert read.label_check.outcome == "fail"
    assert "8" in read.label_check.detail


def test_read_section_names_a_label_that_matches():
    assert _read(_summary(_clean())).label_check.outcome == "pass"


def test_read_section_refuses_an_obligation_with_no_quote_and_names_it():
    blank = _clean().model_copy(update={"evidence": "   "})
    with pytest.raises(SectionReadError, match="Section 7.*paragraph '7.1'"):
        _read(_summary(blank))


def test_read_section_asks_about_a_paragraph_that_cannot_be_an_anchor():
    odd = _clean().model_copy(update={"paragraph": "paragraph seven"})
    read = _read(_summary(odd))
    (question,) = read.questions
    assert read.facts == {}
    assert "paragraph seven" in question.question
    assert question.about.anchor == SECTION7.paragraphs[0].anchor


def test_read_section_gives_the_same_facts_for_a_reworded_requirement():
    reworded = _clean().model_copy(update={"requirement": "Tell the FSOA at once"})
    (first,) = _read(_summary(_clean())).facts
    (second,) = _read(_summary(reworded)).facts
    assert first == second


def _twins(*requirements: str) -> list[Obligation]:
    return [_clean().model_copy(update={"requirement": r}) for r in requirements]


def test_read_section_keeps_both_duties_of_two_obligations_with_one_quote():
    read = _read(_summary(*_twins("Notify the FSOA of a major incident", "Log each incident")))
    (fact,) = read.facts.values()
    assert fact.attributes["requirement"] == [
        "Notify the FSOA of a major incident",
        "Log each incident",
    ]
    assert read.result.fact_ids == [fact.id, fact.id]
    assert read.count_check.outcome == "pass"
    assert "2 of 2 obligations" in read.count_check.detail


def test_requirement_mismatches_name_the_paragraph_whose_requirements_are_short():
    summary = _summary(*_twins("One duty", "Another duty"))
    read = _read(summary)
    (fact,) = read.facts.values()
    assert requirement_mismatches(summary.obligations, read.facts) == []
    short = Fact.build(
        context=FACT_CONTEXT,
        **{
            **{k: v for k, v in fact.to_json().items() if k not in {"id", "schema"}},
            "attributes": {"requirement": ["One duty"], "deadline": fact.attributes["deadline"]},
        },
    )
    assert requirement_mismatches(summary.obligations, {short.id: short}) == ["7.1"]


def test_requirement_mismatches_name_a_paragraph_with_no_fact_at_all():
    summary = _summary(_clean())
    assert requirement_mismatches(summary.obligations, {}) == ["7.1"]
