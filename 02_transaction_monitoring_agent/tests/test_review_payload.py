"""The review interrupt's payload and resume value, and the store namespaces."""

import json

import pytest
from pydantic import ValidationError
from support import DANA, TODAY, accept, small_request

from fsi_common.records import SignOff, carry_over, record_digest
from utils.records import FACT_CONTEXT
from utils.review import (
    CitedFact,
    InvalidNamespaceLabelError,
    ReviewMismatchError,
    ReviewRequest,
    ReviewResponse,
    decisions_namespace,
    sign_offs_namespace,
)


@pytest.fixture(scope="module")
def small():
    return small_request()


def test_the_payload_is_json_and_reads_back_with_the_topics_declaration(small):
    payload = small.request.to_payload()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["statements"][0]["facts"][0]["fact"]["schema"] == "fact.v1"
    assert ReviewRequest.model_validate(payload, context=FACT_CONTEXT) == small.request


def test_only_assessments_need_a_decision_each_once_in_the_order_the_brief_cites_them(small):
    ids = [
        c.fact.attributes.get("proposed_decision") and c.fact.subject.anchor
        for c in small.request.assessments
    ]
    assert ids == ["tx:TX-1001", "tx:TX-1003"]
    every = [c for s in small.request.statements for c in s.facts]
    assert len(every) == 6
    assert {c.fact.kind for c in every} == {"transaction_assessment", "customer_attribute"}


def test_a_cited_fact_carries_the_digest_of_its_own_fact(small):
    cited = small.request.statements[0].facts[0]
    with pytest.raises(ValidationError, match="seen_digest is not the digest"):
        CitedFact(
            fact=cited.fact,
            seen_digest=small.request.brief_digest,
            unit_text=cited.unit_text,
            carry=cited.carry,
        )


def test_a_cited_fact_whose_carry_is_not_what_carry_over_gives_is_refused(small):
    cited = small.request.statements[0].facts[0]
    other = small.request.statements[1].facts[0].fact
    earlier = accept(other)
    with pytest.raises(ValidationError, match="carry is not what carry_over gives"):
        CitedFact(
            fact=cited.fact,
            seen_digest=record_digest(cited.fact),
            unit_text=cited.unit_text,
            carry=carry_over(earlier, other),
        )


def test_an_earlier_decision_on_the_same_assessment_is_carried_into_the_payload():
    first = small_request()
    earlier = accept(first.request.assessments[0].fact)
    again = small_request(carry_from={earlier.subject_id: earlier})
    carry = again.request.assessments[0].carry
    assert (carry.outcome, carry.decision.id, carry.decision.reviewer.name) == (
        "carried",
        earlier.id,
        "Dana Whitfield",
    )
    assert again.request.to_payload()["statements"][0]["facts"][0]["carry"]["outcome"] == "carried"


def test_the_resume_value_carries_one_reviewer(small):
    fact = small.request.assessments[0].fact
    response = ReviewResponse(reviewer=DANA, decisions=[accept(fact)])
    assert (
        ReviewResponse.model_validate(response.model_dump(mode="json", by_alias=True)) == response
    )


def test_the_resume_value_refuses_another_persons_decision(small):
    fact = small.request.assessments[0].fact
    with pytest.raises(ValidationError, match="the reviewer's own"):
        ReviewResponse(
            reviewer={"name": "Sam Okafor", "role": "Compliance Analyst"},
            decisions=[accept(fact)],
        )


def test_the_resume_value_refuses_a_machine_reviewer():
    with pytest.raises(ValidationError, match="is a model, a program or a service"):
        ReviewResponse(reviewer={"name": "Claude", "role": "Reviewer"}, decisions=[])


def test_a_sign_off_for_another_digest_is_refused(small):
    sign_off = SignOff.build(
        brief_id=small.request.brief_id,
        brief_digest="sha256:" + "9" * 64,
        reviewer=DANA,
        date=TODAY,
        outcome="signed",
        assumptions=[],
    )
    with pytest.raises(ReviewMismatchError, match="not for the brief and digest"):
        ReviewResponse(reviewer=DANA, decisions=[], sign_off=sign_off).check_against(small.request)


def test_namespaces_hold_a_customer_and_refuse_labels_the_store_cannot_hold():
    assert decisions_namespace("USR-001") == ("transaction-monitoring", "decisions", "USR-001")
    assert sign_offs_namespace("USR-001") == ("transaction-monitoring", "sign-offs", "USR-001")
    with pytest.raises(InvalidNamespaceLabelError, match="'USR.001'"):
        decisions_namespace("USR.001")
    with pytest.raises(InvalidNamespaceLabelError):
        sign_offs_namespace("")
