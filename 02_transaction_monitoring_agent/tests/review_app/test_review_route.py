"""The review route's actions build decisions and sign-offs, and refuse what cannot be recorded."""

import pytest
from support import DANA as DANA_FIELDS
from support import TODAY, small_request

from context.questions import question_for_missing
from context.reader import read_stream
from fsi_common.records import Person
from review_app.drafts import Draft
from review_app.review_model import ReviewModel
from review_app.review_route import (
    ReviewInputError,
    answer_question,
    build_response,
    check_assumption,
    compose_amendment,
    decide_assessment,
)
from utils import db
from utils.review import final_of

DANA = Person(**DANA_FIELDS)
SAM = Person(name="Sam Okafor", role="Fraud Analyst")
SMALL = small_request()
REQUEST = SMALL.request
FIRST, SECOND = (c.fact for c in REQUEST.assessments)


def decide(fact=FIRST, **changes):
    options = {
        "outcome": "accept",
        "reason": "The customer rang to say she is in Lisbon.",
        "final": None,
        "wording": None,
        "person": DANA,
        "on": TODAY,
    }
    return decide_assessment(REQUEST, fact.id, **{**options, **changes})


def test_an_accept_is_the_persons_decision_on_the_assessment_as_the_request_showed_it():
    decision = decide()
    assert decision.outcome == "accept" and decision.subject_id == FIRST.id
    assert decision.reviewer == DANA and decision.date == TODAY
    assert decision.reason == "The customer rang to say she is in Lisbon."
    assert decision.judged["attributes"]["risk_score"] == FIRST.attributes["risk_score"]
    assert decision.amendment is None


def test_the_reason_is_the_persons_own_words_and_is_trimmed_and_cannot_be_blank():
    assert decide(reason="  Checked.  ").reason == "Checked."
    for blank in ("", "   ", None):
        with pytest.raises(ReviewInputError, match="Write your reason in your own words"):
            decide(reason=blank)


def test_an_amend_is_the_persons_own_decision_and_wording_and_says_which_decision_it_is():
    decision = decide(outcome="amend", final="block", wording="She says she never went to Lisbon.")
    assert decision.outcome == "amend"
    assert decision.amendment == "Block. She says she never went to Lisbon."
    assert final_of(decision.amendment) == "block"


def test_an_amend_needs_approve_or_block_and_words():
    with pytest.raises(ReviewInputError, match="Choose approve or block"):
        decide(outcome="amend", final=None, wording="Words.")
    with pytest.raises(ReviewInputError, match="Choose approve or block"):
        decide(outcome="amend", final="hold", wording="Words.")
    with pytest.raises(ReviewInputError, match="your own decision in your own words"):
        decide(outcome="amend", final="approve", wording="  ")


def test_the_amendment_text_and_its_decision_read_back():
    assert compose_amendment("approve", "  Fine.  ") == "Approve. Fine."
    assert final_of("Approve. Fine.") == "approve"
    assert final_of("Block. Not her.") == "block"
    assert final_of("Something else") is None
    assert final_of(None) is None


def test_a_reject_needs_only_a_reason():
    assert decide(outcome="reject").outcome == "reject"


@pytest.mark.parametrize("outcome", ["", "approve", "agree", None])
def test_an_outcome_other_than_accept_amend_or_reject_is_refused(outcome):
    with pytest.raises(ReviewInputError, match="agree, change or disagree"):
        decide(outcome=outcome)


def test_a_transaction_that_is_not_on_the_brief_or_is_a_profile_field_is_refused():
    profile = next(
        c.fact for s in REQUEST.statements for c in s.facts if c.fact.kind == "customer_attribute"
    )
    for fact_id in ("fact:" + "0" * 16, profile.id):
        with pytest.raises(ReviewInputError, match="not on this brief"):
            decide_assessment(
                REQUEST,
                fact_id,
                outcome="accept",
                reason="x",
                final=None,
                wording=None,
                person=DANA,
                on=TODAY,
            )


def question():
    stream = read_stream("USR-001")
    return question_for_missing(
        stream.unit_of["tx:TX-1002"], db.get("transactions", transaction_id="TX-1002")
    )


def with_question():
    q = question()
    return REQUEST.model_copy(update={"open_questions": [q]}), q


def test_an_answer_to_a_question_is_the_persons_answer_and_what_it_rests_on():
    request, q = with_question()
    decision = answer_question(
        request,
        q.id,
        final="approve",
        answer="It is her usual commute.",
        reason="Called her.",
        person=DANA,
        on=TODAY,
    )
    assert (decision.outcome, decision.answer, decision.reason) == (
        "answer",
        "Approve. It is her usual commute.",
        "Called her.",
    )
    assert final_of(decision.answer) == "approve"


@pytest.mark.parametrize("final", [None, "", "maybe"])
def test_an_answer_states_approve_or_block_beside_the_words(final):
    request, q = with_question()
    with pytest.raises(ReviewInputError, match="Choose approve or block"):
        answer_question(
            request, q.id, final=final, answer="Words.", reason="Why.", person=DANA, on=TODAY
        )


@pytest.mark.parametrize(("answer", "reason"), [("", "Why."), ("Yes.", ""), (None, None)])
def test_an_answer_needs_both_the_answer_and_what_it_rests_on(answer, reason):
    request, q = with_question()
    with pytest.raises(ReviewInputError, match="in your own words"):
        answer_question(
            request, q.id, final="block", answer=answer, reason=reason, person=DANA, on=TODAY
        )


def test_a_question_that_is_not_on_the_brief_is_refused_by_name():
    with pytest.raises(ReviewInputError, match="not on this brief"):
        answer_question(
            REQUEST,
            "question:" + "0" * 16,
            final="block",
            answer="A",
            reason="B",
            person=DANA,
            on=TODAY,
        )
    with pytest.raises(ReviewInputError, match="not on this brief"):
        check_assumption(REQUEST, "question:" + "0" * 16, "Words.")


def test_an_assumption_is_the_persons_words_and_cannot_be_blank():
    request, q = with_question()
    assert check_assumption(request, q.id, "  Treat it as approved.  ") == "Treat it as approved."
    with pytest.raises(ReviewInputError, match="the assumption in your own words"):
        check_assumption(request, q.id, "")


def model_and_draft(*, decide_all=True, request=REQUEST, who=DANA):
    draft = Draft()
    if decide_all:
        for fact in (FIRST, SECOND):
            d = decide(fact, person=who)
            draft.facts[d.subject_id] = d
    return ReviewModel(request, draft, viewer=who, earlier={}), draft


def sign(model, draft, **changes):
    options = {"outcome": "signed", "reason": None, "person": DANA, "on": TODAY}
    return build_response(
        REQUEST if model is None else model.request, model, draft, **{**options, **changes}
    )


def test_signing_sends_every_decision_and_the_sign_off_of_the_person_at_the_digest_they_read():
    model, draft = model_and_draft()
    response = sign(model, draft)
    assert response.reviewer == DANA
    assert {d.subject_id for d in response.decisions} == {FIRST.id, SECOND.id}
    assert response.sign_off.outcome == "signed" and response.sign_off.reason is None
    assert (response.sign_off.brief_id, response.sign_off.brief_digest) == (
        REQUEST.brief_id,
        REQUEST.brief_digest,
    )


def test_a_brief_with_a_transaction_undecided_cannot_be_signed_and_says_why():
    model, draft = model_and_draft(decide_all=False)
    with pytest.raises(ReviewInputError, match="2 transactions without a decision"):
        sign(model, draft)


def test_a_brief_with_a_disagreement_can_only_be_returned():
    model, draft = model_and_draft()
    rejection = decide(FIRST, outcome="reject", reason="Not her.")
    draft.facts[FIRST.id] = rejection
    model = ReviewModel(REQUEST, draft, viewer=DANA, earlier={})
    with pytest.raises(ReviewInputError, match="You disagreed with 1 transaction"):
        sign(model, draft)
    response = sign(model, draft, outcome="returned", reason="Assess them again.")
    assert response.sign_off.outcome == "returned"
    assert response.sign_off.reason == "Assess them again."


def test_a_return_needs_the_persons_reason():
    model, draft = model_and_draft()
    with pytest.raises(ReviewInputError, match="why you are returning the brief"):
        sign(model, draft, outcome="returned", reason="  ")


def test_a_sign_off_or_return_must_be_chosen():
    model, draft = model_and_draft()
    with pytest.raises(ReviewInputError, match="sign the brief or return it"):
        sign(model, draft, outcome="approved")


def test_decisions_another_person_made_are_not_sent_under_this_persons_name():
    model, draft = model_and_draft(who=SAM)
    with pytest.raises(ReviewInputError, match="Sam Okafor, Fraud Analyst"):
        sign(ReviewModel(REQUEST, draft, viewer=DANA, earlier={}), draft)
    assert model.cannot_sign_because() is None
