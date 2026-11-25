"""The review as the pages show it: one object gives the sentence, the tiles and every badge."""

import pytest
from support import DANA as DANA_FIELDS
from support import TODAY, accept, small_request

from context.questions import question_for_missing
from context.reader import read_stream
from fsi_common.records import Decision, Person
from review_app.drafts import Draft
from review_app.review_model import ReviewModel
from utils import db
from utils.review import NOT_ANSWERED

DANA = Person(**DANA_FIELDS)
SAM = Person(name="Sam Okafor", role="Fraud Analyst")


def model_for(small=None, draft=None, viewer=DANA, questions=(), earlier=None):
    small = small or small_request()
    request = small.request.model_copy(update={"open_questions": list(questions)})
    return ReviewModel(request, draft or Draft(), viewer=viewer, earlier=earlier or {})


def facts(small):
    return [c.fact for c in small.request.assessments]


def question():
    stream = read_stream("USR-001")
    return question_for_missing(
        stream.unit_of["tx:TX-1002"], db.get("transactions", transaction_id="TX-1002")
    )


def draft_of(*fact_decisions, answers=()):
    return Draft(
        facts={d.subject_id: d for d in fact_decisions}, answers={a.subject_id: a for a in answers}
    )


def test_with_nothing_decided_every_assessment_needs_a_decision_and_the_brief_cannot_be_signed():
    model = model_for()
    answer = model.answer()
    assert answer.sentence == (
        "The brief for Priya Shah has 2 transactions to decide. 2 still need your decision "
        "before it can be signed."
    )
    assert [(t.label, t.value, t.status) for t in answer.tiles] == [
        ("Transactions", "2", "normal"),
        ("Decided", "0 of 2", "needs_person"),
        ("Questions settled", "0 of 0", "normal"),
    ]
    assert model.cannot_sign_because() == (
        "The brief cannot be signed yet: 2 transactions without a decision."
    )


def test_a_decision_of_the_viewer_counts_and_the_sentence_and_the_tiles_change_together():
    small = small_request()
    first, _ = facts(small)
    model = model_for(small, draft_of(accept(first)))
    assert model.answer().sentence.endswith("1 still needs your decision before it can be signed.")
    assert model.answer().tiles[1].value == "1 of 2"
    assert model.fact_states[first.id].kind == "yours"


def test_every_transaction_decided_and_no_question_makes_the_brief_ready_to_sign():
    small = small_request()
    model = model_for(small, draft_of(*(accept(f) for f in facts(small))))
    assert model.answer().sentence.endswith(
        "Every transaction and question is settled, so it is ready for you to sign."
    )
    assert model.answer().tiles[1].status == "normal"
    assert model.cannot_sign_because() is None


def test_a_rejection_settles_the_transaction_but_the_brief_can_only_be_returned():
    small = small_request()
    first, second = facts(small)
    rejection = Decision.on(first, outcome="reject", reason="Wrong.", reviewer=DANA, date=TODAY)
    model = model_for(small, draft_of(rejection, accept(second)))
    assert "You disagreed with 1 transaction, so the brief can be returned but not signed." in (
        model.answer().sentence
    )
    assert model.cannot_sign_because().startswith("You disagreed with 1 transaction")


def test_a_decision_another_person_made_does_not_count_for_the_viewer():
    small = small_request()
    first, _ = facts(small)
    other = Decision.on(first, outcome="accept", reason="Fine.", reviewer=SAM, date=TODAY)
    model = model_for(small, draft_of(other))
    assert model.fact_states[first.id].kind == "needs"
    assert model_for(small, draft_of(other), viewer=None).fact_states[first.id].kind == "needs"


def test_a_decision_on_the_assessment_as_it_was_before_it_changed_does_not_count():
    small = small_request()
    first, _ = facts(small)
    changed = first.model_copy(deep=True)
    object.__setattr__(changed, "attributes", {**first.attributes, "reason": "Other words."})
    stale = Decision.on(changed, outcome="accept", reason="Ok.", reviewer=DANA, date=TODAY)
    assert model_for(small, draft_of(stale)).fact_states[first.id].kind == "needs"


def test_an_earlier_decision_that_still_holds_is_carried_and_one_that_changed_asks_again():
    first = small_request()
    earlier = accept(facts(first)[0])
    carried = small_request(carry_from={earlier.subject_id: earlier})
    state = model_for(carried).fact_states[earlier.subject_id]
    assert (state.kind, state.decision.id, state.settled) == ("carried", earlier.id, True)
    stale = Decision.on(
        facts(first)[0].model_copy(update={"quote": '"user_id": "USR-009"'}),
        outcome="accept",
        reason="Old.",
        reviewer=DANA,
        date=TODAY,
    )
    assert stale.judged_digest != earlier.judged_digest


def test_the_next_transaction_to_decide_is_found_after_the_current_one_and_wraps_round():
    small = small_request()
    first, second = facts(small)
    model = model_for(small)
    assert model.next_waiting(first.id) == second.id
    assert model.next_waiting(second.id) == first.id
    done = model_for(small, draft_of(accept(second)))
    assert done.next_waiting(first.id) is None


def test_an_open_question_is_waiting_until_it_is_answered_and_an_assumption_does_not_settle_it():
    small = small_request()
    q = question()
    waiting = model_for(small, questions=[q])
    assert [s.kind for s in waiting.question_states] == ["open"]
    assert waiting.answer().tiles[2].value == "0 of 1"
    answer = Decision.on(
        q,
        outcome="answer",
        answer="Approve. It is her.",
        reason="Called her.",
        reviewer=DANA,
        date=TODAY,
    )
    answered = model_for(small, draft_of(answers=[answer]), questions=[q])
    assert [s.kind for s in answered.question_states] == ["answered"]
    assert answered.answer().tiles[2].value == "1 of 1"
    assumed = model_for(small, Draft(assumptions={q.id: "Treat it as approved."}), questions=[q])
    assert [s.kind for s in assumed.question_states] == ["open"]
    assert assumed.question_states[0].assumption == "Treat it as approved."
    assert assumed.answer().tiles[2].value == "0 of 1"
    beside = model_for(
        small, Draft(answers={q.id: answer}, assumptions={q.id: "Words."}), questions=[q]
    )
    assert [s.kind for s in beside.question_states] == ["answered"]
    assert beside.question_states[0].assumption == "Words."


def test_a_held_answer_that_names_neither_approve_nor_block_leaves_the_question_open():
    small = small_request()
    q = question()
    vague = Decision.on(
        q, outcome="answer", answer="Maybe, ask her.", reason="Unsure.", reviewer=DANA, date=TODAY
    )
    model = model_for(small, draft_of(answers=[vague]), questions=[q])
    assert [s.kind for s in model.question_states] == ["open"]
    assert model.answer().tiles[2].value == "0 of 1"


def test_a_question_settled_earlier_by_words_that_name_neither_stays_open():
    small = small_request()
    q = question()
    vague = Decision.on(
        q, outcome="answer", answer="Maybe, ask her.", reason="Unsure.", reviewer=DANA, date=TODAY
    )
    settled = q.model_copy(update={"state": "answered", "decision_id": vague.id})
    model = model_for(small, questions=[settled], earlier={vague.id: vague})
    assert [s.kind for s in model.question_states] == ["open"]


def test_the_brief_with_an_unanswered_question_cannot_be_signed_and_says_so():
    small = small_request()
    model = model_for(small, draft_of(*(accept(f) for f in facts(small))), questions=[question()])
    assert model.cannot_sign_because() == (
        f"The brief cannot be signed yet: 1 question {NOT_ANSWERED}."
    )
    assumed = model_for(
        small,
        Draft(
            facts={d.subject_id: d for d in (accept(f) for f in facts(small))},
            assumptions={question().id: "Treat it as approved."},
        ),
        questions=[question()],
    )
    assert assumed.cannot_sign_because() == model.cannot_sign_because()


def test_a_draft_answer_to_a_question_not_on_the_brief_is_ignored():
    small = small_request()
    q = question()
    answer = Decision.on(
        q,
        outcome="answer",
        answer="Approve. It is her.",
        reason="Called her.",
        reviewer=DANA,
        date=TODAY,
    )
    model = model_for(small, draft_of(answers=[answer]))
    assert model.valid_answers(draft_of(answers=[answer])) == {}


def test_a_viewer_who_is_nobody_decides_nothing():
    small = small_request()
    first, _ = facts(small)
    model = model_for(small, draft_of(accept(first)), viewer=None)
    assert model.answer().tiles[1].value == "0 of 2"


@pytest.mark.parametrize(("count", "noun"), [(1, "transaction"), (2, "transactions")])
def test_the_sentence_counts_in_the_singular_and_the_plural(count, noun):
    small = small_request()
    only = small.request.model_copy(update={"statements": small.request.statements[:count]})
    model = ReviewModel(only, Draft(), viewer=DANA, earlier={})
    assert f"has {count} {noun} to decide." in model.answer().sentence
