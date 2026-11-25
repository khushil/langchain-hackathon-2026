"""The words a decision, a check and a time are shown in; the decision a finished brief keeps."""

from support import DANA as DANA_FIELDS
from support import small_request

from fsi_common.records import CheckResult, Decision, Person, SignOff
from review_app.views import (
    assessment_view,
    by_whom,
    check_label,
    decision_by,
    decision_line,
    difference_label,
    final_word,
    mark_quote,
    pick_decision,
    sentence_end,
    transaction_of,
    when_words,
)

DANA = Person(**DANA_FIELDS)
SAM = Person(name="Sam Okafor", role="Fraud Analyst")
SMALL = small_request()
FACT = SMALL.request.assessments[0].fact


def decision(who=DANA, date="2026-11-25", outcome="accept", **more):
    return Decision.on(FACT, outcome=outcome, reason="Because.", reviewer=who, date=date, **more)


def sign_off(who=DANA, date="2026-11-25"):
    return SignOff.build(
        brief_id="brief:" + "1" * 16,
        brief_digest="sha256:" + "2" * 64,
        reviewer=who,
        date=date,
        outcome="signed",
        assumptions=[],
    )


def test_the_decision_the_sign_offs_reviewer_made_on_the_sign_off_date_stands_over_a_later_one():
    mine, theirs = decision(DANA, "2026-11-25"), decision(SAM, "2026-11-26")
    assert pick_decision([mine, theirs], sign_off()) == mine


def test_without_a_decision_of_the_signers_the_latest_stands_and_the_later_recorded_of_a_tie():
    early, late = decision(SAM, "2026-11-24"), decision(SAM, "2026-11-26", outcome="reject")
    assert pick_decision([early, late], sign_off(DANA, "2026-11-25")) == late
    first, second = decision(DANA), decision(SAM)
    assert pick_decision([first, second], None) == second
    assert pick_decision([], None) is None


def test_a_decision_is_told_with_its_outcome_reviewer_and_date_and_you_only_for_the_viewer():
    made = decision()
    assert decision_by(made) == "Agreed by Dana Whitfield, Head of Compliance"
    assert decision_by(made, DANA) == "Agreed by you"
    assert decision_by(made, SAM) == "Agreed by Dana Whitfield, Head of Compliance"
    assert by_whom(made, None) == "Dana Whitfield, Head of Compliance"
    assert decision_line(made, DANA) == "Agreed by you, on 25 November 2026"


def test_what_a_person_stands_on_is_said_in_words_for_each_outcome():
    assert final_word(decision()) == "Proposal agreed"
    assert final_word(decision(outcome="reject")) == "Proposal disagreed with"
    changed = decision(outcome="amend", amendment="Block. Not her.")
    assert final_word(changed) == "Block"
    assert final_word(decision(outcome="amend", amendment="Hmm.")) == "Changed"


def test_a_decision_knows_its_transaction_from_what_was_judged():
    assert transaction_of(decision()) == "TX-1001"


def test_a_time_and_a_closing_full_stop_are_written_as_a_person_reads_them():
    assert when_words("2026-10-09T21:03") == "9 October 2026, 21:03"
    assert sentence_end(" Fine ") == "Fine."
    assert sentence_end("Fine?") == "Fine?"


def test_a_check_and_a_changed_field_are_named_in_words_never_by_code():
    check = CheckResult(check="decision-follows-score.v1", outcome="pass", detail="ok")
    assert check_label(check) == "The proposed decision follows the score, blocking from 70"
    other = CheckResult(check="new-check.v2", outcome="pass", detail="ok")
    assert check_label(other) == "New check"
    assert difference_label("attributes.risk_score") == "Risk score"
    assert difference_label("attributes.something_new") == "Something new"
    assert difference_label("quote") == "The quoted fields"
    assert difference_label("checks.score-in-range.v1") == (
        "The risk score is a whole number from 0 to 100 (result)"
    )


def test_the_quote_is_found_in_a_line_whatever_the_spacing_and_not_found_when_it_is_not_there():
    segments = mark_quote('{"a": 1,   "b": 2}', '"a": 1, "b": 2')
    assert [(s.text, s.marked) for s in segments] == [
        ("{", False),
        ('"a": 1,   "b": 2', True),
        ("}", False),
    ]
    assert mark_quote('{"a": 1}', '"a": 9') is None
    assert mark_quote("text", "  ") is None


def test_the_view_of_an_assessment_reads_the_profile_the_statement_cites():
    cited = SMALL.request.assessments[0]
    view = assessment_view(SMALL.request.statements[0], cited)
    assert (view.tx_id, view.merchant, view.amount) == ("TX-1001", "FreshMart Express", "18.4 GBP")
    assert view.home_country == "GB"
    assert view.usual_spend == "10 to 150"
    assert view.proposed == "Approve" and not view.lowered
