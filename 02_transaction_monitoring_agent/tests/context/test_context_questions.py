"""An assessment that fails a check, or a transaction with none, becomes a question."""

from context.checks import RecordedAssessment
from context.facts import assessment_fact
from context.questions import question_for_failed, question_for_missing
from context.reader import read_stream
from fsi_common.records import OpenQuestion
from utils import db

STREAM = read_stream("USR-001", end="2026-10-10")  # TX-1001 to TX-1003
ROW = db.get("transactions", transaction_id="TX-1003")
UNIT = STREAM.unit_of["tx:TX-1003"]


def failed_fact(**changes):
    base = {
        "risk_score": 90,
        "model_confidence": 0.9,
        "confidence": 0.9,
        "confidence_checks": [],
        "agent_decision": "approve",
        "reason": "Words.",
    }
    recorded = RecordedAssessment(transaction_id="TX-1003", **{**base, **changes})
    return assessment_fact(
        STREAM, ROW, recorded, model="m", prompt_version="p-1", observed_on="2026-11-25"
    )


def test_a_decision_that_disagrees_with_its_score_is_a_contradiction_for_a_fraud_analyst():
    fact = failed_fact()
    question = question_for_failed(fact, UNIT, ROW)
    assert isinstance(question, OpenQuestion)
    assert question.reason == "contradiction"
    assert question.ask_role == "Fraud analyst"
    assert question.about.anchor == "tx:TX-1003"
    assert question.state == "open" and question.decision_id is None
    assert question.cites == [fact.id, UNIT.id]
    assert "TX-1003" in question.question and "Hotel Miramar Lisboa" in question.question
    assert "decision-follows-score.v1" in question.why_unknown
    assert "approve" in question.why_unknown and "90" in question.why_unknown


def test_a_score_that_cannot_be_read_is_an_unreadable_assessment():
    fact = failed_fact(risk_score=300, agent_decision="block")
    assert question_for_failed(fact, UNIT, ROW).reason == "unreadable"


def test_the_question_asked_twice_about_the_same_fact_has_the_same_id():
    fact = failed_fact()
    assert question_for_failed(fact, UNIT, ROW).id == question_for_failed(fact, UNIT, ROW).id


def test_a_transaction_with_no_assessment_is_missing_data_with_high_priority():
    question = question_for_missing(UNIT, ROW)
    assert question.reason == "missing_data"
    assert question.priority == "high"
    assert question.cites == [UNIT.id]
    assert "TX-1003" in question.question
    assert "recorded no assessment" in question.why_unknown
