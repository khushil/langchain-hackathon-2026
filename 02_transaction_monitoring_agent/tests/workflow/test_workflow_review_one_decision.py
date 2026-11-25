"""A transaction is decided only by a person's approve or block, and by one decision at a time.

The forms cannot write a vague answer, a vague amendment or two decisions on one transaction, but a
client that resumes the registered graph can, so the engine refuses or ignores each of them.
"""

import pytest
from engine_fakes import DANA, REVIEW_DATE, Harness, ScriptedModels, label_script, respond

from fsi_common.records import Decision, SignOff
from utils.review import NOT_ANSWERED, ReviewMismatchError, ReviewResponse, settles

NO_PROPOSAL = label_script() | {"TX-2004": None}


def answer(question, words):
    return Decision.on(
        question,
        outcome="answer",
        answer=words,
        reason="Rang her.",
        reviewer=DANA,
        date=REVIEW_DATE,
    )


def decide(fact, outcome, **more):
    return Decision.on(
        fact,
        outcome=outcome,
        reason="Checked.",
        reviewer=DANA,
        date=REVIEW_DATE,
        **more,
    )


def response(request, decisions, outcome="signed"):
    sign_off = SignOff.build(
        brief_id=request.brief_id,
        brief_digest=request.brief_digest,
        reviewer=DANA,
        date=REVIEW_DATE,
        outcome=outcome,
        assumptions=[],
        reason="Rewrite it." if outcome == "returned" else None,
    )
    return ReviewResponse(reviewer=DANA, decisions=decisions, sign_off=sign_off)


def assessments_of(request):
    return [c.fact for c in request.assessments if c.carry.outcome != "carried"]


def test_a_decision_settles_only_when_it_states_approve_or_block():
    harness = Harness(ScriptedModels(NO_PROPOSAL))
    request = harness.review_request(harness.start("USR-002"))
    question = request.open_questions[0]
    fact = request.assessments[0].fact
    assert settles(answer(question, "Block. Not her."))
    assert not settles(answer(question, "Maybe, ask her."))
    assert settles(decide(fact, "accept"))
    assert settles(decide(fact, "amend", amendment="Approve. Hers."))
    assert not settles(decide(fact, "amend", amendment="Hold it until she calls back."))
    assert not settles(decide(fact, "reject"))


def test_a_vague_answer_kept_by_a_response_with_no_signature_does_not_settle_the_question():
    harness = Harness(ScriptedModels(NO_PROPOSAL))
    config = harness.start("USR-002")
    request = harness.review_request(config)
    question = request.open_questions[0]
    vague = answer(question, "Maybe, ask her.")
    harness.resume(
        config,
        ReviewResponse(
            reviewer=DANA,
            decisions=[*(decide(f, "accept") for f in assessments_of(request)), vague],
        ),
    )
    again = harness.review_request(config)
    assert [q.state for q in again.open_questions] == ["open"]
    done = [decide(f, "accept") for f in assessments_of(again)]
    with pytest.raises(ReviewMismatchError, match=NOT_ANSWERED):
        harness.resume(config, response(again, done))
    assert harness.graph.get_state(config).next == ("review",)
    assert harness.values(config).get("sign_off") in (None, {})


def test_a_vague_answer_carried_from_a_returned_run_does_not_settle_the_question():
    harness = Harness(ScriptedModels(NO_PROPOSAL))
    first = harness.start("USR-002")
    request = harness.review_request(first)
    vague = answer(request.open_questions[0], "Maybe, ask her.")
    harness.resume(first, response(request, [vague], outcome="returned"))
    second = harness.start("USR-002")
    later = harness.review_request(second)
    assert [q.state for q in later.open_questions] == ["open"]
    done = [decide(f, "accept") for f in assessments_of(later)]
    with pytest.raises(ReviewMismatchError, match=NOT_ANSWERED):
        harness.resume(second, response(later, done))
    assert harness.graph.get_state(second).next == ("review",)


def test_an_answer_that_states_approve_or_block_carries_to_a_later_run_and_settles_it():
    harness = Harness(ScriptedModels(NO_PROPOSAL))
    first = harness.start("USR-002")
    request = harness.review_request(first)
    firm = answer(request.open_questions[0], "Block. Not her.")
    harness.resume(first, response(request, [firm], outcome="returned"))
    later = harness.review_request(harness.start("USR-002"))
    assert [q.state for q in later.open_questions] == ["answered"]


def test_an_amendment_that_names_neither_approve_nor_block_is_refused():
    harness = Harness()
    config = harness.start("USR-001", end="2026-10-19")
    request = harness.review_request(config)
    facts = assessments_of(request)
    vague = decide(facts[0], "amend", amendment="Hold it until she calls back.")
    decisions = [vague, *(decide(f, "accept") for f in facts[1:])]
    with pytest.raises(ReviewMismatchError, match="approve or block"):
        harness.resume(config, response(request, decisions))
    assert harness.graph.get_state(config).next == ("review",)


def test_two_decisions_on_one_transaction_are_refused_naming_it():
    harness = Harness()
    config = harness.start("USR-001", end="2026-10-19")
    request = harness.review_request(config)
    facts = assessments_of(request)
    decisions = [decide(facts[0], "reject"), *(decide(f, "accept") for f in facts)]
    with pytest.raises(ReviewMismatchError, match=facts[0].subject.anchor):
        harness.resume(config, response(request, decisions))
    assert harness.graph.get_state(config).next == ("review",)


def test_two_decisions_on_one_question_are_refused():
    harness = Harness(ScriptedModels(NO_PROPOSAL))
    config = harness.start("USR-002")
    request = harness.review_request(config)
    question = request.open_questions[0]
    decisions = [
        *(decide(f, "accept") for f in assessments_of(request)),
        answer(question, "Block. Not her."),
        answer(question, "Maybe, ask her."),
    ]
    with pytest.raises(ReviewMismatchError, match=question.about.anchor):
        harness.resume(config, response(request, decisions))


def test_a_response_with_one_decision_on_each_transaction_still_signs():
    harness = Harness(ScriptedModels(NO_PROPOSAL))
    config = harness.start("USR-002")
    harness.resume(config, respond(harness.review_request(config)))
    assert harness.values(config)["sign_off"]["outcome"] == "signed"


def test_the_sign_check_does_not_trust_a_question_marked_settled_by_a_vague_earlier_answer():
    from workflow.review import validate_response

    harness = Harness(ScriptedModels(NO_PROPOSAL))
    config = harness.start("USR-002")
    request = harness.review_request(config)
    vague = answer(request.open_questions[0], "Maybe, ask her.")
    marked = request.open_questions[0].model_copy(
        update={"state": "answered", "decision_id": vague.id}
    )
    shown = request.model_copy(update={"open_questions": [marked], "history": [vague]})
    done = response(shown, [decide(f, "accept") for f in assessments_of(shown)])
    with pytest.raises(ReviewMismatchError, match=NOT_ANSWERED):
        validate_response(done, shown, harness.values(config))
    firm = answer(request.open_questions[0], "Block. Not her.")
    marked_firm = marked.model_copy(update={"decision_id": firm.id})
    ok = request.model_copy(update={"open_questions": [marked_firm], "history": [firm]})
    validate_response(
        response(ok, [decide(f, "accept") for f in assessments_of(ok)]), ok, harness.values(config)
    )
