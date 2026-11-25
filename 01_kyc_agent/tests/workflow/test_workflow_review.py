"""The review step: sign-off, return, partial decisions, carry-over and refusals."""

import time

import pytest
from engine_fakes import REVIEW_DATE, REVIEWER, Harness, bundle_records, respond
from kyc_fakes import ScriptedReader, reading_of

from fsi_common.bundle_checks import check_bundle
from fsi_common.records import Decision, Fact, OpenQuestion, SignOff
from utils.kyc_state import ReviewMismatchError
from utils.records import FACT_CONTEXT
from workflow.review import validate_response

THREE = ("CUST-003", "CUST-016", "CUST-001")


def proposals(request):
    return [c for s in request.statements for c in s.facts if c.fact.kind == "proposal"]


def test_the_run_stops_at_the_review_with_each_proposal_beside_its_evidence():
    harness = Harness()
    config = harness.start(*THREE)
    request = harness.review_request(config)
    assert harness.graph.get_state(config).next == ("review",)
    assert len(request.statements) == 3
    assert {c.carry.outcome for s in request.statements for c in s.facts} == {"fresh"}
    values = harness.values(config)
    assert not values.get("sign_off") and not values.get("decisions")
    first = request.statements[0]
    assert first.heading == "CUST-001 Sarah Mitchell"
    assert "proposed low risk and approve" in first.text
    for cited in first.facts:
        assert cited.fact.quote in cited.unit_text


def test_a_signed_review_stores_each_decision_under_its_customer_and_ends_the_run():
    harness = Harness()
    config = harness.start(*THREE)
    request = harness.review_request(config)
    harness.resume(config, respond(request))
    state = harness.graph.get_state(config)
    values = state.values
    assert state.next == ()
    assert values["sign_off"]["outcome"] == "signed"
    assert values["sign_off"]["brief_digest"] == request.brief_digest
    assert len(values["decisions"]) == 3 + len(request.open_questions)
    for customer in THREE:
        stored = harness.store.search(("kyc-onboarding", "decisions", customer), limit=100)
        assert stored, customer
        for item in stored:
            judged = item.value["judged"]
            place = judged["subject"] if "subject" in judged else judged["about"]
            assert place["anchor"].partition(":")[2].startswith(customer)
    everything = harness.store.search(("kyc-onboarding", "decisions"), limit=100)
    assert sorted(i.key for i in everything) == sorted(values["decisions"])
    signed = harness.store.search(("kyc-onboarding", "sign-offs"), limit=10)
    assert [i.key for i in signed] == [values["sign_off"]["id"]]


def test_a_returned_review_keeps_the_reason_and_ends_the_run():
    harness = Harness()
    config = harness.start(*THREE)
    request = harness.review_request(config)
    harness.resume(config, respond(request, outcome="returned", decide="reject"))
    values = harness.values(config)
    assert values["sign_off"]["outcome"] == "returned"
    assert values["sign_off"]["reason"] == "Returned for another look."


def test_decisions_without_a_sign_off_are_kept_and_the_run_waits_again():
    harness = Harness()
    config = harness.start(*THREE)
    request = harness.review_request(config)
    harness.resume(config, respond(request).model_copy(update={"sign_off": None}))
    state = harness.graph.get_state(config)
    assert state.next == ("review",)
    again = harness.review_request(config)
    assert {c.carry.outcome for c in proposals(again)} == {"carried"}
    harness.resume(config, respond(again))
    assert harness.values(config)["sign_off"]["outcome"] == "signed"


def test_a_later_run_carries_an_unchanged_decision_and_asks_again_about_a_changed_one():
    harness = Harness()
    first = harness.start(*THREE)
    harness.resume(first, respond(harness.review_request(first)))
    wrong = reading_of("CUST-016")
    wrong = wrong.model_copy(
        update={"date_of_birth": wrong.date_of_birth.model_copy(update={"value": "1971-04-18"})}
    )
    later = Harness(ScriptedReader(readings={"CUST-016": wrong}), store=harness.store)
    second = later.start(*THREE)
    request = later.review_request(second)
    by_customer = {c.fact.subject.anchor: c for c in proposals(request)}
    assert by_customer["row:CUST-001"].carry.outcome == "carried"
    assert by_customer["row:CUST-003"].carry.outcome == "carried"
    changed = by_customer["row:CUST-016"]
    assert changed.carry.outcome == "ask_again"
    assert changed.carry.decision.reviewer.name == REVIEWER["name"]
    assert "attributes.settled" in changed.carry.differences
    assert changed.fact.attributes["settled"] is False


def test_decisions_about_one_customer_do_not_reach_a_run_on_another():
    harness = Harness()
    first = harness.start("CUST-001")
    harness.resume(first, respond(harness.review_request(first)))
    second = harness.start("CUST-004")
    assert {c.carry.outcome for c in proposals(harness.review_request(second))} == {"fresh"}


def test_a_decision_in_the_new_run_replaces_the_carried_one_on_the_same_fact():
    harness = Harness()
    first = harness.start("CUST-001")
    harness.resume(first, respond(harness.review_request(first)))
    second = harness.start("CUST-001")
    request = harness.review_request(second)
    target = proposals(request)[0]
    sam = {"name": "Sam Okoye", "role": "Compliance Officer"}
    amend = Decision.on(
        target.fact,
        outcome="amend",
        reason="Checked the lists again.",
        reviewer=sam,
        date="2026-11-26",
        amendment="Low risk, approve with a review in a year.",
    )
    harness.resume(second, respond(request, reviewer=sam).model_copy(update={"decisions": [amend]}))
    values = harness.values(second)
    on_target = [d for d in values["decisions"].values() if d["subject_id"] == target.fact.id]
    assert [(d["outcome"], d["reviewer"]["name"]) for d in on_target] == [("amend", "Sam Okoye")]


def test_an_open_question_answered_in_the_review_moves_to_answered_and_stays_so():
    harness = Harness()
    config = harness.start("CUST-018")
    request = harness.review_request(config)
    [question] = request.open_questions
    assert question.state == "open"
    harness.resume(config, respond(request, answer="A different person."))
    values = harness.values(config)
    settled = OpenQuestion.model_validate(values["open_questions"][question.id])
    assert settled.state == "answered"
    assert settled.decision_id in values["decisions"]
    assert values["decisions"][settled.decision_id]["answer"] == "A different person."
    again = harness.review_request(harness.start("CUST-018"))
    assert again.open_questions[0].state == "answered"


def test_a_sign_off_for_another_digest_is_refused_before_anything_is_stored():
    harness = Harness()
    config = harness.start(*THREE)
    request = harness.review_request(config)
    wrong = SignOff.build(
        brief_id=request.brief_id,
        brief_digest="sha256:" + "0" * 64,
        reviewer=REVIEWER,
        date=REVIEW_DATE,
        outcome="signed",
        assumptions=[],
    )
    with pytest.raises(ReviewMismatchError, match="not for the brief and digest"):
        validate_response(
            respond(request).model_copy(update={"sign_off": wrong}), request, harness.values(config)
        )


def test_a_decision_on_something_the_reviewer_was_not_shown_is_refused():
    harness = Harness()
    config = harness.start("CUST-001", "CUST-004")
    request = harness.review_request(config)
    values = harness.values(config)
    shown = {c.fact.id for s in request.statements for c in s.facts}
    stray = (
        next(
            Fact.model_validate(c[0], context=FACT_CONTEXT)
            for c in values["facts"].values()
            if c[0]["id"] not in shown
        )
        if len(shown) < len(values["facts"])
        else None
    )
    if stray is None:  # every fact is cited by a statement: use a fact from another run
        other = Harness()
        other_values = other.values(other.start("CUST-003"))
        stray = next(
            Fact.model_validate(c[0], context=FACT_CONTEXT)
            for c in other_values["facts"].values()
            if c[0]["kind"] == "screening"
        )
    decision = Decision.on(
        stray, outcome="accept", reason="Looks right.", reviewer=REVIEWER, date=REVIEW_DATE
    )
    response = respond(request)
    response = response.model_copy(update={"decisions": [*response.decisions, decision]})
    with pytest.raises(ReviewMismatchError, match="was not shown"):
        validate_response(response, request, values)


def test_a_decision_on_a_changed_version_of_a_fact_is_refused():
    harness = Harness()
    config = harness.start("CUST-001")
    request = harness.review_request(config)
    cited = proposals(request)[0].fact
    stale = Decision.on(
        cited, outcome="accept", reason="Checked.", reviewer=REVIEWER, date=REVIEW_DATE
    ).model_copy(update={"seen_digest": "sha256:" + "1" * 64})
    response = respond(request, decide=None).model_copy(update={"decisions": [stale]})
    with pytest.raises(ReviewMismatchError, match="before it changed"):
        validate_response(response, request, harness.values(config))


def test_a_signed_sign_off_with_an_open_question_neither_answered_nor_accepted_is_refused():
    harness = Harness()
    config = harness.start("CUST-018")
    request = harness.review_request(config)
    blind = respond(request)
    blind = blind.model_copy(
        update={"decisions": [d for d in blind.decisions if d.outcome != "answer"]}
    )
    with pytest.raises(ReviewMismatchError, match=request.open_questions[0].id):
        validate_response(blind, request, harness.values(config))


def test_a_question_may_be_named_as_an_assumption_instead_of_answered():
    harness = Harness()
    config = harness.start("CUST-018")
    request = harness.review_request(config)
    response = respond(request, assume=True)
    validate_response(response, request, harness.values(config))
    harness.resume(config, response)
    assert harness.values(config)["sign_off"]["assumptions"][0]["question_id"] == (
        request.open_questions[0].id
    )


def test_an_assumption_on_a_question_the_brief_does_not_carry_is_refused():
    harness = Harness()
    config = harness.start("CUST-001")
    request = harness.review_request(config)
    odd = SignOff.build(
        brief_id=request.brief_id,
        brief_digest=request.brief_digest,
        reviewer=REVIEWER,
        date=REVIEW_DATE,
        outcome="signed",
        assumptions=[{"question_id": "question:0000000000000000", "words": "Assume it."}],
    )
    with pytest.raises(ReviewMismatchError, match="question:0000000000000000"):
        validate_response(
            respond(request).model_copy(update={"sign_off": odd}), request, harness.values(config)
        )


def test_a_returned_sign_off_needs_no_answer_to_an_open_question():
    harness = Harness()
    config = harness.start("CUST-018")
    request = harness.review_request(config)
    validate_response(
        respond(request, outcome="returned", decide="reject", assume=True),
        request,
        harness.values(config),
    )


def test_the_state_after_a_clean_signed_run_passes_the_contracts_bundle_check():
    harness = Harness()
    config = harness.start(*THREE, "CUST-018")
    harness.resume(config, respond(harness.review_request(config)))
    assert check_bundle(bundle_records(harness.values(config)), where="state") == []


def _undecided_response(request, **kwargs):
    return respond(request, decide=None, **kwargs)


def test_a_signed_sign_off_with_no_proposal_decided_is_refused_naming_each_one():
    harness = Harness()
    config = harness.start("CUST-001", "CUST-004")
    request = harness.review_request(config)
    ids = [c.fact.id for c in proposals(request)]
    with pytest.raises(ReviewMismatchError, match="no decision") as caught:
        validate_response(_undecided_response(request), request, harness.values(config))
    assert all(i in str(caught.value) for i in ids)


def test_the_run_service_refuses_the_same_sign_off_and_the_run_still_waits():
    from workflow.runs import KycRuns

    runs = KycRuns(models=ScriptedReader())
    thread_id = runs.start({"request": "Review", "customer_ids": ["CUST-001"]})
    deadline = time.monotonic() + 20
    while runs.status(thread_id) != "awaiting_review" and time.monotonic() < deadline:
        time.sleep(0.01)
    request = runs.review_request(thread_id)
    with pytest.raises(ReviewMismatchError, match="no decision"):
        runs.submit(thread_id, _undecided_response(request))
    assert runs.status(thread_id) == "awaiting_review"
    assert runs.submit(thread_id, respond(request)) == "signed"


def test_a_signed_sign_off_with_a_rejected_proposal_is_refused():
    harness = Harness()
    config = harness.start("CUST-001")
    request = harness.review_request(config)
    with pytest.raises(ReviewMismatchError, match="rejected"):
        validate_response(respond(request, decide="reject"), request, harness.values(config))


def test_one_undecided_proposal_among_decided_ones_is_enough_to_refuse():
    harness = Harness()
    config = harness.start("CUST-001", "CUST-004")
    request = harness.review_request(config)
    response = respond(request)
    kept = [d for d in response.decisions if d.subject_id != proposals(request)[1].fact.id]
    with pytest.raises(ReviewMismatchError, match=proposals(request)[1].fact.id):
        validate_response(
            response.model_copy(update={"decisions": kept}), request, harness.values(config)
        )


def test_a_carried_decision_counts_as_decided_and_a_carried_rejection_does_not():
    harness = Harness()
    first = harness.start("CUST-001")
    harness.resume(first, respond(harness.review_request(first)))
    second = harness.start("CUST-001")
    request = harness.review_request(second)
    validate_response(_undecided_response(request), request, harness.values(second))
    third = harness.start("CUST-004")
    rejected = harness.review_request(third)
    harness.resume(third, respond(rejected, outcome="returned", decide="reject"))
    fourth = harness.start("CUST-004")
    again = harness.review_request(fourth)
    assert {c.carry.outcome for c in proposals(again)} == {"carried"}
    with pytest.raises(ReviewMismatchError, match="rejected"):
        validate_response(_undecided_response(again), again, harness.values(fourth))
