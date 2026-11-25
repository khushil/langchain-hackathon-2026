"""Tests of the marker check: a marked paragraph is never closed as holding no fact."""

import pytest

from context.accounting import (
    NO_FACT_REASON,
    account_for_units,
    marked_no_fact_reason,
)
from context.marker_check import (
    marked_without_obligation,
    unconfirmed_questions,
    unmarked_obligation_questions,
)
from context.reader import Paragraph, paragraph_unit, read_document
from fsi_common.records import CheckResult, Fact
from utils.records import FACT_CONTEXT
from workflow.closing import marked_reasons

DOCUMENT = read_document("PS26-4")
SECTION9 = DOCUMENT.section("9")
SOURCE = DOCUMENT.source
PARAGRAPHS9 = list(SECTION9.paragraphs)


def _fact(number: str, *, quote: str | None = None, outcome: str = "pass") -> Fact:
    anchor = f"para:{number}"
    paragraph = DOCUMENT.paragraph(anchor)
    return Fact.build(
        context=FACT_CONTEXT,
        kind="obligation",
        subject={"source_id": SOURCE.id, "anchor": anchor},
        quote=quote or paragraph.text.split(".")[0],
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


def test_a_marked_paragraph_with_no_obligation_fact_is_returned_with_its_marker():
    (found,) = marked_without_obligation(PARAGRAPHS9, [_fact("9.1")])
    assert (found.paragraph.number, found.marker) == ("9.3", "must")


def test_the_paragraphs_come_back_in_the_order_given_each_with_its_own_marker():
    paragraphs = [*SECTION9.paragraphs, *DOCUMENT.section("8").paragraphs]
    found = marked_without_obligation(paragraphs, [])
    assert [(m.paragraph.number, m.marker) for m in found] == [
        ("9.3", "must"),
        ("8.1", "must"),
        ("8.2", "must"),
        ("8.3", "must"),
        ("8.5", "must"),
    ]


def test_a_marked_paragraph_with_an_obligation_fact_is_not_returned():
    assert marked_without_obligation(PARAGRAPHS9, [_fact("9.3")]) == []


def test_a_fact_that_failed_its_check_does_not_mean_the_paragraph_has_an_obligation():
    failed = _fact("9.3", outcome="fail")
    assert not failed.passed_checks
    (found,) = marked_without_obligation(PARAGRAPHS9, [failed])
    assert found.paragraph.number == "9.3"
    assert marked_without_obligation(PARAGRAPHS9, [failed, _fact("9.3")]) == []


def test_an_unmarked_paragraph_with_no_fact_is_not_returned():
    unmarked = [p for p in PARAGRAPHS9 if p.number in {"9.1", "9.2", "9.4"}]
    assert marked_without_obligation(unmarked, []) == []


def test_a_fact_on_another_paragraph_does_not_cover_a_marked_one():
    (found,) = marked_without_obligation(PARAGRAPHS9, [_fact("9.1"), _fact("8.1")])
    assert found.paragraph.number == "9.3"


def test_unconfirmed_question_names_the_paragraph_and_the_marker_and_rests_on_the_paragraph():
    marked = marked_without_obligation(PARAGRAPHS9, [])
    (question,) = unconfirmed_questions(marked, source=SOURCE)
    assert question.about.anchor == "para:9.3" and question.about.source_id == SOURCE.id
    assert "paragraph 9.3" in question.question and '"must"' in question.question
    assert "read again" in question.why_unknown and "paragraph 9.3" in question.why_unknown
    assert question.cites == [paragraph_unit(SOURCE, PARAGRAPHS9[2]).id]
    assert question.reason == "ambiguous_meaning"
    assert (question.state, question.priority, question.ask_role) == (
        "open",
        "high",
        "Head of Compliance",
    )
    assert question.decision_id is None


def test_one_unconfirmed_question_for_each_paragraph_with_its_own_marker():
    paragraphs = [*DOCUMENT.section("8").paragraphs, *PARAGRAPHS9]
    marked = marked_without_obligation(paragraphs, [])
    questions = unconfirmed_questions(marked, source=SOURCE)
    assert [q.about.anchor for q in questions] == [
        "para:8.1",
        "para:8.2",
        "para:8.3",
        "para:8.5",
        "para:9.3",
    ]
    assert len({q.id for q in questions}) == 5


def test_the_same_unconfirmed_question_has_the_same_id_on_every_build():
    marked = marked_without_obligation(PARAGRAPHS9, [])
    first = unconfirmed_questions(marked, source=SOURCE)
    again = unconfirmed_questions(marked, source=SOURCE)
    assert [q.id for q in first] == [q.id for q in again]
    assert [q.to_json() for q in first] == [q.to_json() for q in again]


def test_an_obligation_fact_on_an_unmarked_paragraph_gives_one_question_resting_on_the_fact():
    fact = _fact("9.1", quote="Small firms, as defined in paragraph 2.3, may meet the requirements")
    (question,) = unmarked_obligation_questions(PARAGRAPHS9, [fact], source=SOURCE)
    assert question.about.anchor == "para:9.1"
    assert question.cites == [fact.id]
    assert question.reason == "inferred_only"
    assert "paragraph 9.1" in question.question
    assert "place an obligation on the firm" in question.question
    assert fact.quote in question.question
    assert "must" in question.why_unknown and "shall" in question.why_unknown
    assert (question.state, question.priority) == ("open", "medium")


def test_an_obligation_fact_on_a_marked_paragraph_gives_no_question():
    assert unmarked_obligation_questions(PARAGRAPHS9, [_fact("9.3")], source=SOURCE) == []


def test_several_obligation_facts_on_one_unmarked_paragraph_give_one_question_resting_on_all():
    first = _fact("9.1", quote="Small firms, as defined in paragraph 2.3")
    second = _fact("9.1", quote="may meet the requirements in paragraphs 4.1, 4.2, 5.1 and 6.1")
    (question,) = unmarked_obligation_questions(PARAGRAPHS9, [first, second], source=SOURCE)
    assert question.cites == [first.id, second.id]
    assert first.quote in question.question and second.quote in question.question
    assert question.question.count("place an obligation on the firm") == 1
    assert question.about.anchor == "para:9.1"


def test_one_question_for_each_unmarked_paragraph_that_gave_an_obligation_fact():
    paragraphs = [
        *DOCUMENT.section("2").paragraphs,
        *DOCUMENT.section("6").paragraphs,
        *PARAGRAPHS9,
    ]
    facts = [
        _fact("2.5"),
        _fact("6.6", quote="first"),
        _fact("6.6", quote="second"),
        _fact("9.1"),
        _fact("9.1", quote="another"),
        _fact("9.3"),
    ]
    questions = unmarked_obligation_questions(paragraphs, facts, source=SOURCE)
    assert [q.about.anchor for q in questions] == ["para:2.5", "para:6.6", "para:9.1"]
    assert [len(q.cites) for q in questions] == [1, 2, 2]
    assert len({q.id for q in questions}) == 3


def test_the_same_fact_twice_is_listed_once_and_the_question_keeps_its_id_on_every_build():
    fact = _fact("9.1")
    (once,) = unmarked_obligation_questions(PARAGRAPHS9, [fact], source=SOURCE)
    (twice,) = unmarked_obligation_questions(PARAGRAPHS9, [fact, fact], source=SOURCE)
    assert twice.cites == [fact.id] and twice.id == once.id


def test_a_fact_that_failed_its_check_on_an_unmarked_paragraph_is_still_asked_about():
    failed = _fact("9.1", outcome="fail")
    (question,) = unmarked_obligation_questions(PARAGRAPHS9, [failed], source=SOURCE)
    assert question.cites == [failed.id]


def test_a_fact_of_another_section_is_not_asked_about_by_this_section():
    assert unmarked_obligation_questions(PARAGRAPHS9, [_fact("2.5")], source=SOURCE) == []


def test_the_reason_a_marked_paragraph_gives_names_the_marker_and_is_not_the_plain_no_fact_reason():
    reason = marked_no_fact_reason("must")
    assert '"must"' in reason and "open question" in reason
    assert reason != NO_FACT_REASON
    assert marked_no_fact_reason("is required to") != reason


def test_account_for_units_gives_a_unit_its_own_reason_and_the_rest_the_common_one():
    units = [paragraph_unit(SOURCE, p) for p in PARAGRAPHS9]
    own = marked_no_fact_reason("must")
    result = account_for_units(SOURCE, units, units, [_fact("9.1")], reasons={"para:9.3": own})
    reasons = {u.anchor: u.reason for u in result.accounting.without_facts}
    assert reasons == {"para:9.2": NO_FACT_REASON, "para:9.3": own, "para:9.4": NO_FACT_REASON}
    assert result.accounting.units_in == 4
    assert result.accounting.with_facts == ["para:9.1"]
    assert result.line == "PS26-4: 4 of 4 units accounted for (1 with facts, 3 without)"


def test_a_reason_for_a_unit_that_has_a_fact_is_not_used_and_the_counts_still_close():
    units = [paragraph_unit(SOURCE, p) for p in PARAGRAPHS9]
    result = account_for_units(
        SOURCE, units, units, [_fact("9.1"), _fact("9.3")], reasons={"para:9.3": "unused"}
    )
    assert [u.reason for u in result.accounting.without_facts] == [NO_FACT_REASON] * 2
    assert result.accounting.with_facts == ["para:9.1", "para:9.3"]


@pytest.mark.parametrize(
    "marker", ["must", "shall", "is required to", "are required to", "will need to"]
)
def test_the_reason_quotes_every_marker_it_is_given(marker):
    assert f'"{marker}"' in marked_no_fact_reason(marker)


SHALL = Paragraph(number="9.9", section="9", text="Every firm shall file a return each year.")


def _state_asking_about(questions) -> dict:
    return {"open_questions": {q.id: q.to_json() for q in questions}}


def test_a_paragraph_whose_marker_is_shall_is_named_with_shall_in_the_question_and_the_reason():
    (found,) = marked_without_obligation([SHALL], [])
    assert found.marker == "shall"
    questions = unconfirmed_questions([found], source=SOURCE)
    (question,) = questions
    assert '"shall"' in question.question and '"shall"' in question.why_unknown
    reasons = marked_reasons(_state_asking_about(questions), [SHALL], facts=[])
    assert reasons == {"para:9.9": marked_no_fact_reason("shall")}
    assert '"shall"' in reasons["para:9.9"]


def test_the_question_for_a_failed_fact_says_no_obligation_that_passed_its_checks_was_read():
    (found,) = marked_without_obligation(PARAGRAPHS9, [_fact("9.3", outcome="fail")])
    (question,) = unconfirmed_questions([found], source=SOURCE)
    assert "passed its checks" in question.question and "passed its checks" in question.why_unknown


def test_the_reverse_question_does_not_say_the_brief_holds_a_fact_that_failed_a_check():
    failed = _fact("9.1", outcome="fail")
    (question,) = unmarked_obligation_questions(PARAGRAPHS9, [failed], source=SOURCE)
    assert "passed its checks" in question.impact
    assert "in the brief" not in question.impact.replace("the brief cites it only", "")
