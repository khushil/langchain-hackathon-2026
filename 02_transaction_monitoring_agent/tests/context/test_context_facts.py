"""Facts: the customer's profile read by code, and an assessment read from the assessor's record."""

import json

import pytest

from context.checks import CHECK_NAMES, RecordedAssessment
from context.errors import AssessmentReadError
from context.facts import assessment_fact, customer_facts
from context.reader import read_stream
from fsi_common.records import Fact, judged_digest
from tools.decisions import _confidence_checks
from utils import db
from utils.records import FACT_CONTEXT

STREAM = read_stream("USR-001")
ROW = db.get("transactions", transaction_id="TX-1003")


def recorded(**changes) -> RecordedAssessment:
    base = {
        "risk_score": 45,
        "model_confidence": 0.9,
        "confidence": 0.5,
        "confidence_checks": _confidence_checks(45, ROW, "USR-001", (30, 70)),
        "agent_decision": "approve",
        "reason": "A hotel abroad that the customer has not told us about.",
    }
    return RecordedAssessment(transaction_id="TX-1003", **{**base, **changes})


def build(**changes) -> Fact:
    return assessment_fact(
        STREAM,
        ROW,
        recorded(**changes),
        model="claude-sonnet-5-5",
        prompt_version="assessor-1",
        observed_on="2026-11-25",
    )


def test_the_profile_row_gives_one_documented_fact_for_each_of_its_seven_fields():
    facts = customer_facts(STREAM)
    assert [f.attributes["field"] for f in facts] == [
        "name",
        "home_country",
        "city",
        "currency",
        "usual_amount_range",
        "usual_categories",
        "customer_since",
    ]
    unit_text = STREAM.unit_text[STREAM.unit_of["customer:USR-001"].id]
    for fact in facts:
        assert fact.kind == "customer_attribute"
        assert fact.subject.anchor == "customer:USR-001"
        assert fact.status.status == "documented"
        assert fact.provenance.model is None
        assert fact.quote in unit_text
        assert fact.passed_checks


def test_a_customer_fact_holds_the_value_as_the_row_gives_it():
    by_field = {f.attributes["field"]: f for f in customer_facts(STREAM)}
    assert by_field["home_country"].attributes["value"] == "GB"
    assert by_field["home_country"].quote == '"home_country": "GB"'
    assert by_field["usual_amount_range"].attributes == {
        "field": "usual_amount_range",
        "low": 10,
        "high": 150,
    }
    assert by_field["usual_amount_range"].quote == '"usual_amount_range": [10, 150]'
    assert by_field["usual_categories"].attributes["value"] == [
        "groceries",
        "transport",
        "restaurants",
        "streaming",
    ]
    assert by_field["customer_since"].attributes["value"] == 2020


def test_every_customer_fact_of_both_customers_has_its_quote_in_its_row():
    for user in ("USR-001", "USR-002"):
        stream = read_stream(user)
        text = stream.unit_text[stream.unit_of[f"customer:{user}"].id]
        facts = customer_facts(stream)
        assert len(facts) == 7
        assert all(f.passed_checks for f in facts)
        assert all(
            json.dumps(json.loads(text)[f.attributes["field"]], ensure_ascii=False) in f.quote
            for f in facts
        )


def test_an_assessment_is_a_fact_about_the_transaction_quoting_its_own_fields():
    fact = build()
    unit_text = STREAM.unit_text[STREAM.unit_of["tx:TX-1003"].id]
    assert fact.kind == "transaction_assessment"
    assert fact.subject.anchor == "tx:TX-1003"
    assert fact.quote in unit_text
    assert fact.quote.startswith('"user_id": "USR-001", "timestamp": "2026-10-09T21:03"')
    assert [c.check for c in fact.checks] == list(CHECK_NAMES)
    assert fact.passed_checks


def test_an_assessment_carries_what_the_assessor_recorded_and_what_the_row_says():
    attributes = build().attributes
    assert attributes == {
        "user_id": "USR-001",
        "timestamp": "2026-10-09T21:03",
        "merchant": "Hotel Miramar Lisboa",
        "category": "travel",
        "amount": "380.0",
        "currency": "GBP",
        "country": "PT",
        "channel": "online",
        "risk_score": 45,
        "proposed_decision": "approve",
        "confidence": "0.5",
        "model_confidence": "0.9",
        "confidence_checks": _confidence_checks(45, ROW, "USR-001", (30, 70)),
        "reason": "A hotel abroad that the customer has not told us about.",
    }


def test_an_assessment_is_observed_on_the_day_it_was_recorded_by_the_named_model_and_prompt():
    fact = build()
    assert fact.status.status == "observed"
    assert fact.status.observed_at == "2026-11-25"
    assert fact.provenance.model == "claude-sonnet-5-5"
    assert fact.provenance.prompt_version == "assessor-1"
    assert fact.provenance.extractor.name == "transaction-assessor"
    assert fact.provenance.as_of == STREAM.transaction_source.digest


def test_the_same_transaction_gives_the_same_id_whatever_the_assessor_said():
    first, second = build(), build(risk_score=90, agent_decision="block", reason="Other words.")
    assert first.id == second.id
    assert judged_digest(first) != judged_digest(second)


def test_an_assessment_that_fails_a_check_is_still_a_fact_with_the_failed_check_on_it():
    fact = build(risk_score=101)
    failed = [c.check for c in fact.checks if c.outcome == "fail"]
    assert failed == ["score-in-range.v1", "decision-follows-score.v1", "confidence-checks.v1"]
    assert not fact.passed_checks


@pytest.mark.parametrize("score", [45.5, None, "45", True])
def test_a_score_that_is_not_a_whole_number_is_kept_as_it_was_given_and_fails_its_check(score):
    fact = build(risk_score=score)
    assert fact.attributes["risk_score"] == (
        score if score is None or score is True or isinstance(score, str) else "45.5"
    )
    assert "score-in-range.v1" in [c.check for c in fact.checks if c.outcome == "fail"]


def test_a_record_for_another_transaction_is_refused_by_name():
    other = RecordedAssessment(**{**vars(recorded()), "transaction_id": "TX-1004"})
    with pytest.raises(AssessmentReadError, match="TX-1004.*TX-1003"):
        assessment_fact(
            STREAM, ROW, other, model="m", prompt_version="p-1", observed_on="2026-11-25"
        )


def test_a_fact_reads_back_from_its_json_with_the_topic_declaration():
    fact = build()
    assert Fact.model_validate(fact.to_json(), context=FACT_CONTEXT) == fact
