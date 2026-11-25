"""The plain-code checks on an assessment: each passes a sound one and fails its planted fault."""

import pytest

from context.checks import (
    CHECK_NAMES,
    RecordedAssessment,
    assessment_checks,
    assessment_quote,
    check_confidence_checks,
    check_confidence_range,
    check_decision,
    check_fields,
    check_quote,
    check_score,
)
from context.errors import AssessmentReadError
from context.reader import read_stream
from tools.decisions import _confidence_checks
from utils import db

ROW = db.get("transactions", transaction_id="TX-1003")
LINE = read_stream("USR-001").unit_text[read_stream("USR-001").unit_of["tx:TX-1003"].id]
QUOTE = assessment_quote(ROW)
FIRED = _confidence_checks(45, ROW, "USR-001", (30, 70))


def recorded(**changes) -> RecordedAssessment:
    base = {
        "risk_score": 45,
        "model_confidence": 0.9,
        "confidence": 0.5,
        "confidence_checks": FIRED,
        "agent_decision": "approve",
        "reason": "A hotel abroad that the customer has not told us about.",
    }
    return RecordedAssessment(transaction_id="TX-1003", **{**base, **changes})


def test_the_quote_is_the_rows_own_field_values_from_the_user_to_the_channel():
    assert QUOTE == (
        '"user_id": "USR-001", "timestamp": "2026-10-09T21:03", '
        '"merchant": "Hotel Miramar Lisboa", '
        '"category": "travel", "amount": 380.0, "currency": "GBP", "country": "PT", '
        '"channel": "online"'
    )
    assert QUOTE in LINE


def test_a_sound_assessment_passes_every_check_in_a_fixed_order():
    results = assessment_checks(ROW, LINE, QUOTE, recorded())
    assert [r.check for r in results] == list(CHECK_NAMES)
    assert [r.outcome for r in results] == ["pass"] * len(CHECK_NAMES)
    assert all(r.detail.strip() for r in results)


def test_the_check_names_say_what_they_check_and_carry_a_version():
    assert CHECK_NAMES == (
        "quote-verbatim.v1",
        "fields-in-row.v1",
        "score-in-range.v1",
        "decision-follows-score.v1",
        "confidence-in-range.v1",
        "confidence-checks.v1",
    )


def test_a_quote_that_is_not_in_the_row_fails_the_quote_check():
    result = check_quote(QUOTE.replace("380.0", "38.0"), LINE, anchor="tx:TX-1003")
    assert result.outcome == "fail"
    assert "tx:TX-1003" in result.detail


def test_a_quote_that_names_a_wrong_value_or_an_unknown_field_fails_the_field_check():
    wrong = check_fields(QUOTE.replace("380.0", "38.0"), ROW)
    assert wrong.outcome == "fail" and "amount" in wrong.detail
    unknown = check_fields(QUOTE + ', "tip": 5', ROW)
    assert unknown.outcome == "fail" and "tip" in unknown.detail
    assert check_fields(QUOTE, ROW).outcome == "pass"
    assert check_fields("not json at all", ROW).outcome == "fail"


@pytest.mark.parametrize("score", [0, 5, 45, 69, 70, 100])
def test_a_whole_score_from_0_to_100_passes(score):
    assert check_score(score).outcome == "pass"


@pytest.mark.parametrize("score", [-1, 101, 1000, 45.5, True, "45", None])
def test_anything_else_fails_the_score_check(score):
    assert check_score(score).outcome == "fail"


@pytest.mark.parametrize(
    ("score", "decision", "outcome"),
    [
        (5, "approve", "pass"),
        (29, "approve", "pass"),
        (45, "approve", "pass"),
        (69, "approve", "pass"),
        (70, "block", "pass"),
        (95, "block", "pass"),
        (69, "block", "fail"),
        (70, "approve", "fail"),
        (95, "approve", "fail"),
        (5, "block", "fail"),
        (45, "hold", "fail"),
    ],
)
def test_the_decision_follows_the_starters_rule_block_from_70(score, decision, outcome):
    assert check_decision(score, decision).outcome == outcome


@pytest.mark.parametrize(
    ("model", "final", "outcome"),
    [
        (0.9, 0.5, "pass"),
        (0.0, 0.0, "pass"),
        (1, 1, "pass"),
        (1.2, 0.5, "fail"),
        (0.9, -0.1, "fail"),
        (0.9, "high", "fail"),
        (None, 0.5, "fail"),
    ],
)
def test_both_confidences_lie_from_0_to_1(model, final, outcome):
    assert check_confidence_range(model, final).outcome == outcome


def test_the_starters_confidence_checks_are_recomputed_and_must_match_what_was_recorded():
    assert check_confidence_checks(recorded(), ROW, "USR-001").outcome == "pass"
    forgot = recorded(confidence_checks=[])
    assert check_confidence_checks(forgot, ROW, "USR-001").outcome == "fail"
    not_lowered = recorded(confidence=0.9)
    failed = check_confidence_checks(not_lowered, ROW, "USR-001")
    assert failed.outcome == "fail" and "0.5" in failed.detail


def test_a_check_that_did_not_fire_needs_the_confidence_left_alone():
    clear = db.get("transactions", transaction_id="TX-1001")
    clean = RecordedAssessment(
        transaction_id="TX-1001",
        risk_score=5,
        model_confidence=0.9,
        confidence=0.9,
        confidence_checks=[],
        agent_decision="approve",
        reason="A small shop at home.",
    )
    assert check_confidence_checks(clean, clear, "USR-001").outcome == "pass"


def test_the_detail_of_the_confidence_check_names_each_reason_that_fired():
    result = check_confidence_checks(recorded(), ROW, "USR-001")
    for reason in FIRED:
        assert reason in result.detail


@pytest.mark.parametrize(
    ("changes", "failing"),
    [
        ({"risk_score": 101}, "score-in-range.v1"),
        ({"agent_decision": "block"}, "decision-follows-score.v1"),
        ({"confidence": 7}, "confidence-in-range.v1"),
        ({"confidence": 0.9}, "confidence-checks.v1"),
    ],
)
def test_each_planted_fault_fails_its_own_check_in_the_whole_list(changes, failing):
    results = assessment_checks(ROW, LINE, QUOTE, recorded(**changes))
    assert failing in {r.check for r in results if r.outcome == "fail"}


def test_a_recorded_assessment_is_read_from_the_starters_audit_record():
    audit = {
        "transaction_id": "TX-1003",
        "risk_score": 45,
        "model_confidence": 0.9,
        "confidence": 0.5,
        "confidence_checks": FIRED,
        "agent_decision": "approve",
        "final_decision": "approve",
        "decided_by": "agent",
        "reason": "Unusual.",
    }
    read = RecordedAssessment.from_audit(audit)
    assert read == recorded(reason="Unusual.")
    assert "final_decision" not in vars(read) and "decided_by" not in vars(read)


def test_an_audit_record_that_lacks_a_field_is_refused_by_name():
    with pytest.raises(AssessmentReadError, match="reason"):
        RecordedAssessment.from_audit({"transaction_id": "TX-1003", "risk_score": 3})
