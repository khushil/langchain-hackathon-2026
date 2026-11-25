"""Tests of how the marker check meets the reviewer: failed facts, sign-off, the closing guard."""

import typing

import pytest
from engine_fakes import (
    DOCUMENT,
    Harness,
    ScriptedModels,
    default_summary,
    empty_second_read,
    obliging_second_read,
    respond,
)

from context.errors import AccountingError
from context.marker_check import MarkedParagraph
from context.reader import Paragraph
from fsi_common.records import Fact, OpenQuestion
from sub_agent import SectionSummary
from utils.records import FACT_CONTEXT
from utils.state import ReviewMismatchError
from workflow.closing import close_run
from workflow.engine_state import EngineState
from workflow.review import validate_response
from workflow.second_read import SecondRead, second_read_records, second_read_task


def missing(*numbers: str):
    def read(section):
        base = default_summary(section)
        kept = [o for o in base.obligations if o.paragraph not in numbers]
        return base.model_copy(update={"obligations": kept})

    return read


def paraphrasing(section, number):
    """A second read whose quote is not the paragraph's words."""
    read = obliging_second_read(section, number)
    bad = read.obligations[0].model_copy(update={"evidence": "Firms ought to update contracts"})
    return read.model_copy(update={"obligations": [bad]})


def _facts(values):
    return [
        Fact.model_validate(c, context=FACT_CONTEXT) for cs in values["facts"].values() for c in cs
    ]


def _run(first=missing("9.3"), second=empty_second_read):
    models = ScriptedModels(section=first, paragraph=second)
    harness = Harness(models)
    config = harness.start("9")
    return models, harness, config


def test_a_paraphrased_second_read_fails_its_check_raises_the_question_and_blocks_the_sign_off():
    _, harness, config = _run(second=paraphrasing)
    values = harness.values(config)
    (fact,) = [f for f in _facts(values) if f.subject.anchor == "para:9.3"]
    assert not fact.passed_checks
    (question,) = [OpenQuestion.model_validate(q) for q in values["open_questions"].values()]
    assert question.about.anchor == "para:9.3" and question.reason == "ambiguous_meaning"
    request = harness.review_request(config)
    assert fact.id not in {c.fact.id for s in request.statements for c in s.facts}
    with pytest.raises(ReviewMismatchError, match=question.id):
        harness.resume(config, respond(request))


def test_a_first_read_whose_only_fact_on_a_marked_paragraph_failed_is_read_a_second_time():
    def paraphrased_first(section):
        base = default_summary(section)
        bad = [
            o.model_copy(update={"evidence": "Firms ought to update contracts"})
            if o.paragraph == "9.3"
            else o
            for o in base.obligations
        ]
        return base.model_copy(update={"obligations": bad})

    models, harness, config = _run(first=paraphrased_first, second=obliging_second_read)
    assert models.rereads == ["9.3"]
    values = harness.values(config)
    assert values["open_questions"] == {}
    assert any(f.subject.anchor == "para:9.3" and f.passed_checks for f in _facts(values))


def test_the_brief_cannot_be_signed_while_the_forward_question_is_neither_answered_nor_accepted():
    _, harness, config = _run()
    request = harness.review_request(config)
    (question,) = request.open_questions
    assert question.reason == "ambiguous_meaning"
    with pytest.raises(ReviewMismatchError, match=question.id):
        validate_response(respond(request), request, harness.values(config))
    with pytest.raises(ReviewMismatchError, match=question.id):
        harness.resume(config, respond(request))


def _closing_state_with(question_changes: dict):
    _, harness, config = _run()
    values = dict(harness.values(config))
    ((key, question),) = values["open_questions"].items()
    values["open_questions"] = {key: {**question, **question_changes}}
    return values


def test_closing_accepts_only_a_question_of_the_reason_a_marked_paragraph_is_asked_with():
    close_run(_closing_state_with({}))
    with pytest.raises(AccountingError, match=r"9\.3"):
        close_run(_closing_state_with({"reason": "unresolved_reference"}))
    with pytest.raises(AccountingError, match=r"9\.3"):
        close_run(_closing_state_with({"reason": "inferred_only"}))


def test_a_question_about_another_paragraph_does_not_cover_a_marked_one():
    values = _closing_state_with({})
    ((key, question),) = values["open_questions"].items()
    elsewhere = {**question, "about": {**question["about"], "anchor": "para:9.1"}}
    values["open_questions"] = {key: elsewhere}
    with pytest.raises(AccountingError, match=r"9\.3"):
        close_run(values)


def test_the_count_names_the_sections_marked_paragraphs_not_only_those_read_again():
    models = ScriptedModels(section=missing("4.1"), paragraph=empty_second_read)
    harness = Harness(models)
    values = harness.values(harness.start("4"))
    detail = next(
        v["detail"] for v in values["check_results"].values() if v["check"] == "marker-check.v1"
    )
    assert detail.startswith("1 of 4 paragraph(s) with an obligation marker were read a second")
    assert "(4.1)" in detail


def test_second_reads_are_kept_in_the_order_of_the_paragraph_numbers_not_of_the_text():
    reducer = typing.get_type_hints(EngineState, include_extras=True)["second_reads"].__metadata__[
        0
    ]
    folded = reducer({"para:10.1": {"a": 1}}, {"para:2.4": {"b": 2}, "para:9.3": {"c": 3}})
    assert list(folded) == ["para:2.4", "para:9.3", "para:10.1"]
    again = reducer({"para:2.4": {"b": 2}}, {"para:10.1": {"a": 1}})
    assert list(again) == ["para:2.4", "para:10.1"]


def test_the_request_says_a_word_can_mark_an_obligation_and_does_not_say_it_does():
    text = DOCUMENT.paragraph("para:9.3").text
    section = DOCUMENT.section("9")
    paragraph = next(p for p in section.paragraphs if p.number == "9.3")
    task = second_read_task(section, MarkedParagraph(paragraph=paragraph, marker="must"))
    assert text in task and "can mark an obligation" in task
    assert "marks an obligation" not in task


def test_the_first_line_of_a_second_read_has_the_shape_of_a_section_task():
    paragraph = Paragraph(number="9.9", section="9", text="Firms shall act.")
    task = second_read_task(
        DOCUMENT.section("9"), MarkedParagraph(paragraph=paragraph, marker="shall")
    )
    assert task.startswith("Number: 9\nTitle: ") and "9.9 Firms shall act." in task


def test_the_record_of_a_second_read_names_the_marker_of_the_paragraph_it_read():
    paragraph = Paragraph(number="9.9", section="9", text="Every firm shall file a return.")
    found = MarkedParagraph(paragraph=paragraph, marker="shall")
    summary = SectionSummary(number="9", title="t", summary="s", obligations=[])
    records = second_read_records(
        [SecondRead(found=found, task="asked", summary=summary)], {}, questions=[]
    )
    assert list(records) == ["para:9.9"]
    assert records["para:9.9"]["marker"] == "shall"
    assert records["para:9.9"]["gave_obligation"] is False


def test_gave_obligation_is_about_the_paragraph_read_again_not_the_rest_of_the_section():
    models = ScriptedModels(section=missing("4.1"), paragraph=empty_second_read)
    harness = Harness(models)
    values = harness.values(harness.start("4"))
    assert any(f.subject.anchor == "para:4.2" for f in _facts(values))
    record = values["second_reads"]["para:4.1"]
    assert record["gave_obligation"] is False
    assert record["fact_ids"] == []
    assert record["open_question_id"] is not None


def test_gave_obligation_needs_the_fact_to_have_passed_its_checks():
    _, harness, config = _run(second=paraphrasing)
    values = harness.values(config)
    (fact,) = [f for f in _facts(values) if f.subject.anchor == "para:9.3"]
    record = values["second_reads"]["para:9.3"]
    assert record["gave_obligation"] is False
    assert record["fact_ids"] == [fact.id]
    assert record["open_question_id"] is not None
