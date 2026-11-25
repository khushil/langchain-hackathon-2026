"""The review route's actions: what they build, and what they refuse."""

import pytest
from support import DANA, SMALL, TODAY, new_runs, start_run

from fsi_common.records import Person
from review_app import review_route
from review_app.drafts import Draft
from review_app.review_model import ReviewModel
from review_app.review_route import ReviewInputError


@pytest.fixture(scope="module")
def run():
    runs = new_runs()
    thread = start_run(runs, SMALL)
    return runs.review_request(thread)


def proposal_ids(request):
    return {
        c.fact.subject.anchor.partition(":")[2]: c.fact.id
        for s in request.statements
        for c in s.facts
        if c.fact.kind == "proposal"
    }


def decide(request, customer="CUST-001", **fields):
    options = {"outcome": "accept", "reason": "Checked.", "amendment": None, "person": DANA}
    return review_route.decide_proposal(
        request, proposal_ids(request)[customer], on=TODAY, **{**options, **fields}
    )


def test_a_proposal_is_decided_in_the_persons_words_at_the_digest_shown(run):
    decision = decide(run, outcome="amend", amendment="Low risk, approve.", reason="Ran the lists")
    assert (decision.outcome, decision.amendment) == ("amend", "Low risk, approve.")
    assert decision.reviewer == DANA and decision.date == TODAY
    assert decision.subject_id == proposal_ids(run)["CUST-001"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"reason": "  "}, "your reason"),
        ({"reason": None}, "your reason"),
        ({"outcome": "approve"}, "Choose accept, amend or reject"),
        ({"outcome": "amend"}, "the amended wording"),
        ({"outcome": ""}, "Choose accept, amend or reject"),
    ],
)
def test_a_decision_without_words_or_a_valid_outcome_is_refused(run, change, message):
    with pytest.raises(ReviewInputError, match=message):
        decide(run, **change)


def test_only_a_proposal_is_decided_not_a_screening_or_a_detail(run):
    other = next(
        c.fact.id
        for s in run.statements
        for c in s.facts
        if c.fact.kind in {"screening", "applicant_name"}
    )
    with pytest.raises(ReviewInputError, match="not a proposal"):
        review_route.decide_proposal(
            run, other, outcome="accept", reason="x", amendment=None, person=DANA, on=TODAY
        )


def test_a_fact_that_is_not_on_the_batch_is_refused(run):
    with pytest.raises(ReviewInputError, match="not on this batch"):
        review_route.decide_proposal(
            run, "fact:0000000000000000", outcome="accept", reason="x", amendment=None,
            person=DANA, on=TODAY,
        )  # fmt: skip


def test_a_machine_cannot_be_the_reviewer():
    with pytest.raises(ValueError, match="model, a program or a service"):
        Person(name="Claude", role="Reviewer")


def test_the_review_route_builds_a_decision_on_one_proposal_at_a_time(run):
    names = {name for name in dir(review_route) if not name.startswith("_")}
    assert "decide_proposal" in names
    assert not {n for n in names if "settled" in n or "bulk" in n or "all" in n.split("_")}


def test_an_answer_needs_words_and_a_question_on_the_batch(run):
    question = run.open_questions[0]
    good = review_route.answer_question(
        run, question.id, answer="A different person.", reason="Dates differ.", person=DANA,
        on=TODAY,
    )  # fmt: skip
    assert good.outcome == "answer" and good.answer == "A different person."
    with pytest.raises(ReviewInputError, match="the answer"):
        review_route.answer_question(run, question.id, answer="", reason="x", person=DANA, on=TODAY)
    with pytest.raises(ReviewInputError, match="what the answer rests on"):
        review_route.answer_question(
            run, question.id, answer="x", reason=" ", person=DANA, on=TODAY
        )
    with pytest.raises(ReviewInputError, match="not on this batch"):
        review_route.answer_question(
            run, "question:0000000000000000", answer="x", reason="x", person=DANA, on=TODAY
        )


def test_an_assumption_needs_words_and_a_question_on_the_batch(run):
    question = run.open_questions[0]
    assert review_route.check_assumption(run, question.id, " Assume it. ") == "Assume it."
    with pytest.raises(ReviewInputError, match="the assumption"):
        review_route.check_assumption(run, question.id, "")
    with pytest.raises(ReviewInputError, match="not on this batch"):
        review_route.check_assumption(run, "question:0000000000000000", "x")


def model_of(run, draft=None, viewer=DANA):
    return ReviewModel(run, draft or Draft(), viewer=viewer)


def test_a_batch_cannot_be_signed_while_a_proposal_or_a_question_waits(run):
    model = model_of(run)
    with pytest.raises(ReviewInputError, match="4 proposals without a decision and 2 questions"):
        review_route.build_response(
            run, model, Draft(), outcome="signed", reason=None, person=DANA, on=TODAY
        )


def settled_draft(run, *, by=DANA, answer=True):
    draft = Draft()
    for customer in SMALL:
        draft.facts[proposal_ids(run)[customer]] = decide(run, customer, person=by)
    if answer:
        for question in run.open_questions:
            draft.answers[question.id] = review_route.answer_question(
                run, question.id, answer="A different person.", reason="Dates.", person=by, on=TODAY
            )
    return draft


def test_a_settled_batch_is_signed_with_the_persons_own_decisions(run):
    draft = settled_draft(run)
    response = review_route.build_response(
        run, model_of(run, draft), draft, outcome="signed", reason=None, person=DANA, on=TODAY
    )
    assert response.sign_off.outcome == "signed" and response.sign_off.reviewer == DANA
    assert len(response.decisions) == 6
    assert response.sign_off.brief_digest == run.brief_digest


def test_decisions_made_by_another_person_block_the_sign_off(run):
    draft = settled_draft(run, by=Person(name="Sam Okoye", role="Compliance Officer"))
    with pytest.raises(ReviewInputError, match="Sam Okoye, Compliance Officer"):
        review_route.build_response(
            run, model_of(run, draft, Person(name="Sam Okoye", role="Compliance Officer")), draft,
            outcome="signed", reason=None, person=DANA, on=TODAY,
        )  # fmt: skip


def test_a_rejected_proposal_blocks_signing_but_not_a_return(run):
    draft = settled_draft(run)
    draft.facts[proposal_ids(run)["CUST-001"]] = decide(run, "CUST-001", outcome="reject")
    model = model_of(run, draft)
    with pytest.raises(ReviewInputError, match="rejected 1 proposal"):
        review_route.build_response(
            run, model, draft, outcome="signed", reason=None, person=DANA, on=TODAY
        )
    with pytest.raises(ReviewInputError, match="why you are returning"):
        review_route.build_response(
            run, model, draft, outcome="returned", reason=None, person=DANA, on=TODAY
        )
    returned = review_route.build_response(
        run, model, draft, outcome="returned", reason="Look again.", person=DANA, on=TODAY
    )
    assert returned.sign_off.reason == "Look again."


def test_an_outcome_other_than_signed_or_returned_is_refused(run):
    with pytest.raises(ReviewInputError, match="sign the batch or return it"):
        review_route.build_response(
            run, model_of(run), Draft(), outcome="approved", reason=None, person=DANA, on=TODAY
        )
