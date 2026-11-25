"""Tests of the reverse check: an obligation read from a paragraph with no marker is asked about."""

import pytest
from engine_fakes import (
    DOCUMENT,
    REVIEW_DATE,
    Harness,
    ScriptedModels,
    default_summary,
    respond,
)

from fsi_common.examples.data import REVIEWER
from fsi_common.records import Assumption, Brief, Fact, OpenQuestion, SignOff
from sub_agent import Obligation
from utils.records import FACT_CONTEXT
from utils.state import ReviewMismatchError
from workflow.review import validate_response


def reading_nine_one(section):
    """A read of section 9 that also finds an obligation in 9.1, which has no marker."""
    base = default_summary(section)
    if section.number != "9":
        return base
    text = DOCUMENT.paragraph("para:9.1").text
    extra = Obligation(
        requirement="Meet the small-firm dates",
        paragraph="9.1",
        deadline="by 31 March 2028",
        evidence=text[: text.index(" may ")] + " may meet",
    )
    return base.model_copy(update={"obligations": [extra, *base.obligations]})


def _run(section=reading_nine_one):
    harness = Harness(ScriptedModels(section=section))
    config = harness.start("9")
    return harness, config


def _facts(values):
    return [
        Fact.model_validate(c, context=FACT_CONTEXT) for cs in values["facts"].values() for c in cs
    ]


def test_an_obligation_fact_on_an_unmarked_paragraph_raises_one_question_resting_on_it():
    harness, config = _run()
    values = harness.values(config)
    (fact,) = [f for f in _facts(values) if f.subject.anchor == "para:9.1"]
    (question,) = [OpenQuestion.model_validate(q) for q in values["open_questions"].values()]
    assert question.cites == [fact.id]
    assert question.about.anchor == "para:9.1"
    assert question.reason == "inferred_only" and question.state == "open"
    assert "place an obligation on the firm" in question.question


def test_the_fact_stays_on_the_record_and_in_the_brief_with_its_question():
    harness, config = _run()
    values = harness.values(config)
    (fact,) = [f for f in _facts(values) if f.subject.anchor == "para:9.1"]
    assert fact.passed_checks
    brief = Brief.model_validate(values["draft_brief"])
    assert fact.id in {i for s in brief.statements for i in s.cites}
    assert brief.open_question_ids == sorted(values["open_questions"])
    assert fact.id in {
        c.fact.id for s in harness.review_request(config).statements for c in s.facts
    }


def test_a_fact_on_a_marked_paragraph_raises_no_question():
    harness = Harness(ScriptedModels())
    values = harness.values(harness.start("9"))
    assert values["open_questions"] == {}
    assert any(f.subject.anchor == "para:9.3" for f in _facts(values))


def test_a_run_with_no_such_fact_and_no_reread_asks_nothing_in_the_whole_document():
    models = ScriptedModels()
    harness = Harness(models)
    values = harness.values(harness.start())
    assert values["open_questions"] == {} and models.rereads == []


def test_the_question_does_not_stop_the_paragraph_counting_as_accounted_for():
    harness, config = _run()
    values = harness.values(config)
    document = next(s for s in values["sources"].values() if s["kind"] == "document")
    accounting = values["accounting"][document["id"]]
    assert "para:9.1" in accounting["with_facts"]
    assert accounting["units_in"] == len(accounting["with_facts"]) + len(
        accounting["without_facts"]
    )


def test_the_brief_cannot_be_signed_while_that_question_is_neither_answered_nor_accepted():
    harness, config = _run()
    request = harness.review_request(config)
    (question,) = request.open_questions
    with pytest.raises(ReviewMismatchError, match=question.id):
        validate_response(respond(request), request, harness.values(config))
    with pytest.raises(ReviewMismatchError, match=question.id):
        harness.resume(config, respond(request))


def test_the_brief_can_be_signed_once_the_question_is_accepted_as_an_assumption():
    harness, config = _run()
    request = harness.review_request(config)
    (question,) = request.open_questions
    assert request.statements and question.state == "open"
    response = respond(request)
    accepted = SignOff.build(
        brief_id=request.brief_id,
        brief_digest=request.brief_digest,
        reviewer=REVIEWER,
        date=REVIEW_DATE,
        outcome="signed",
        assumptions=[
            Assumption(
                question_id=question.id, words="Paragraph 9.1 places no obligation on the firm."
            )
        ],
    )
    validate_response(
        response.model_copy(update={"sign_off": accepted}), request, harness.values(config)
    )


def test_the_marker_check_line_counts_paragraphs_with_no_marker_not_facts():
    harness, config = _run()
    results = harness.values(config)["check_results"].values()
    (line,) = [c["detail"] for c in results if c["check"] == "marker-check.v1"]
    assert "1 paragraph(s) with no marker that gave an obligation fact are open questions" in line
