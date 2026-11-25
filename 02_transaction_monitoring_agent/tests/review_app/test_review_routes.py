"""The routes that record what a reviewer decides, and the refusals that keep a decision honest."""

import pytest
from engine_fakes import ScriptedModels, label_script
from review_support import SAM, WINDOW, make_world, marks, record_all, run_path, start_run, text

from fsi_common.records import Decision


def fresh():
    world = make_world()
    thread = start_run(world, "USR-001", **WINDOW)
    request = world.runs.review_request(thread)
    return world, thread, request


def decide(world, thread, request, tx="TX-1001", client=None, **form):
    fact = next(c.fact for c in request.assessments if c.fact.subject.anchor == f"tx:{tx}")
    body = {
        "brief_digest": request.brief_digest,
        "fact_id": fact.id,
        "outcome": "accept",
        "reason": "The customer rang to say she is in Lisbon.",
        **form,
    }
    return (client or world.client()).post(run_path(thread, "decide"), data=body)


def test_an_agreement_is_held_for_the_person_and_the_page_shows_it_as_theirs():
    world, thread, request = fresh()
    response = decide(world, thread, request)
    assert response.status_code == 303
    assert response.headers["location"].endswith("?tx=TX-1002")
    held = world.services.drafts.get(thread, __import__("review_support").DANA)
    assert [d.outcome for d in held.facts.values()] == ["accept"]
    page = world.client().get(run_path(thread, "review"), params={"tx": "TX-1001"})
    words = text(page)
    assert "Your decision: Agreed by you, on 25 November 2026." in words
    assert "Your reason: The customer rang to say she is in Lisbon." in words
    assert "1 of 6" in words and "5 still need your decision" in words


def test_an_own_decision_needs_approve_or_block_and_words_and_the_error_stands_beside_the_form():
    world, thread, request = fresh()
    response = decide(world, thread, request, outcome="amend", wording="")
    assert response.status_code == 422
    words = text(response)
    assert "Choose approve or block for your own decision." in words
    assert "TX-1001, FreshMart Express" in words
    again = decide(world, thread, request, outcome="amend", final="block", wording="Not her.")
    assert again.status_code == 303
    page = world.client().get(run_path(thread, "review"), params={"tx": "TX-1001"})
    assert "Your own decision: Block. Not her." in text(page)


def test_a_missing_reason_is_refused_in_words_and_what_was_typed_is_kept():
    world, thread, request = fresh()
    response = decide(world, thread, request, outcome="reject", reason="  ")
    assert response.status_code == 422
    assert "Write your reason in your own words." in text(response)
    assert 'value="reject" checked' in response.text


def test_nobody_signed_in_cannot_decide():
    world, thread, request = fresh()
    response = decide(world, thread, request, client=world.client(None))
    assert response.status_code == 403
    assert "Sign in with your name and role before you decide on a brief." in text(response)
    assert world.services.drafts.get(thread, __import__("review_support").DANA).facts == {}


def test_a_decision_made_on_a_brief_that_has_changed_is_refused_and_nothing_is_held():
    world, thread, request = fresh()
    response = decide(world, thread, request, brief_digest="sha256:" + "0" * 64)
    assert response.status_code == 409
    assert "The brief changed after you opened it, so nothing was recorded." in text(response)


def test_a_decision_on_a_profile_field_or_an_unknown_fact_is_refused():
    world, thread, request = fresh()
    profile = next(
        c.fact for s in request.statements for c in s.facts if c.fact.kind == "customer_attribute"
    )
    for fact_id in (profile.id, "fact:" + "0" * 16):
        body = {
            "brief_digest": request.brief_digest,
            "fact_id": fact_id,
            "outcome": "accept",
            "reason": "Fine.",
        }
        response = world.client().post(run_path(thread, "decide"), data=body)
        assert response.status_code == 422
        assert "That transaction is not on this brief" in text(response)


def test_another_persons_decisions_are_not_seen_by_this_person_and_cannot_be_signed_for_them():
    world, thread, request = fresh()
    record_all(world, thread, client=world.client(SAM))
    page = world.client().get(run_path(thread, "review"))
    assert "6 still need your decision" in text(page)
    sign = world.client().post(
        run_path(thread, "sign"), data={"brief_digest": request.brief_digest, "outcome": "signed"}
    )
    assert sign.status_code == 422
    assert "The brief cannot be signed yet: 6 transactions without a decision." in text(sign)


def test_signing_with_every_transaction_decided_ends_the_run_and_lands_on_the_signed_page():
    world, thread, request = fresh()
    record_all(world, thread)
    page = world.client().get(run_path(thread, "review"), params={"tab": "signoff"})
    assert "disabled" not in page.text.split('name="outcome" value="signed"')[1].split(">")[0]
    response = world.client().post(
        run_path(thread, "sign"), data={"brief_digest": request.brief_digest, "outcome": "signed"}
    )
    assert response.status_code == 303 and response.headers["location"] == run_path(
        thread, "signed"
    )
    assert world.runs.status(thread) == "signed"
    held = world.runs.result(thread)
    assert held["sign_off"]["reviewer"]["name"] == "Dana Whitfield"
    assert len(held["decisions"]) == 6
    assert world.services.drafts.get(thread, __import__("review_support").DANA).facts == {}


def test_signing_before_every_transaction_is_decided_is_refused_in_words():
    world, thread, request = fresh()
    decide(world, thread, request)
    response = world.client().post(
        run_path(thread, "sign"), data={"brief_digest": request.brief_digest, "outcome": "signed"}
    )
    assert response.status_code == 422
    assert "5 transactions without a decision" in text(response)
    assert world.runs.status(thread) == "awaiting_review"


def test_a_disagreement_means_the_brief_can_only_be_returned_with_a_reason():
    world, thread, request = fresh()
    record_all(world, thread)
    decide(world, thread, request, tx="TX-1003", outcome="reject", reason="Not her.")
    body = {"brief_digest": request.brief_digest, "outcome": "signed"}
    refused = world.client().post(run_path(thread, "sign"), data=body)
    assert refused.status_code == 422 and "You disagreed with 1 transaction" in text(refused)
    no_reason = world.client().post(
        run_path(thread, "sign"), data={**body, "outcome": "returned", "reason": " "}
    )
    assert no_reason.status_code == 422
    assert "Write why you are returning the brief in your own words." in text(no_reason)
    returned = world.client().post(
        run_path(thread, "sign"), data={**body, "outcome": "returned", "reason": "Assess again."}
    )
    assert returned.status_code == 303 and world.runs.status(thread) == "returned"


def question_world():
    world = make_world(ScriptedModels(label_script() | {"TX-1002": None}))
    thread = start_run(world, "USR-001", **WINDOW)
    return world, thread, world.runs.review_request(thread)


def test_a_question_is_answered_in_the_persons_own_words_and_the_brief_can_then_be_signed():
    world, thread, request = question_world()
    record_all(world, thread)
    question = request.open_questions[0]
    unanswered = world.client().post(
        run_path(thread, "sign"), data={"brief_digest": request.brief_digest, "outcome": "signed"}
    )
    assert "1 question not answered or accepted" in text(unanswered)
    empty = world.client().post(
        run_path(thread, "answer"),
        data={
            "brief_digest": request.brief_digest,
            "question_id": question.id,
            "final": "approve",
            "answer": "",
        },
    )
    assert empty.status_code == 422 and "Write the answer in your own words." in text(empty)
    unchosen = world.client().post(
        run_path(thread, "answer"),
        data={
            "brief_digest": request.brief_digest,
            "question_id": question.id,
            "answer": "Her usual commute.",
            "reason": "I rang her and she confirmed it.",
        },
    )
    assert unchosen.status_code == 422 and "Choose approve or block" in text(unchosen)
    done = world.client().post(
        run_path(thread, "answer"),
        data={
            "brief_digest": request.brief_digest,
            "question_id": question.id,
            "final": "approve",
            "answer": "It is her usual commute.",
            "reason": "I rang her and she confirmed it.",
        },
    )
    assert done.status_code == 303
    page = world.client().get(run_path(thread, "review"), params={"tab": "questions"})
    assert "Your answer Approve. It is her usual commute." in text(page)
    signed = world.client().post(
        run_path(thread, "sign"), data={"brief_digest": request.brief_digest, "outcome": "signed"}
    )
    assert signed.status_code == 303
    held = world.runs.result(thread)
    assert next(iter(held["open_questions"].values()))["state"] == "answered"


def test_a_question_can_be_accepted_as_an_assumption_in_the_persons_words():
    world, thread, request = question_world()
    record_all(world, thread)
    question = request.open_questions[0]
    response = world.client().post(
        run_path(thread, "assume"),
        data={
            "brief_digest": request.brief_digest,
            "question_id": question.id,
            "words": "Treat the commute as approved.",
        },
    )
    assert response.status_code == 303
    signed = world.client().post(
        run_path(thread, "sign"), data={"brief_digest": request.brief_digest, "outcome": "signed"}
    )
    assert signed.status_code == 303
    assumptions = world.runs.result(thread)["sign_off"]["assumptions"]
    assert [a["words"] for a in assumptions] == ["Treat the commute as approved."]


def test_a_decision_the_run_did_not_ask_for_is_never_built_by_the_route():
    world, thread, request = question_world()
    response = world.client().post(
        run_path(thread, "answer"),
        data={
            "brief_digest": request.brief_digest,
            "question_id": "question:" + "0" * 16,
            "final": "block",
            "answer": "A",
            "reason": "B",
        },
    )
    assert response.status_code == 422 and "That question is not on this brief" in text(response)
    assert all(
        isinstance(d, Decision) for d in world.services.drafts.get(thread, SAM).facts.values()
    )


@pytest.mark.parametrize("tab", ["brief", "questions", "history", "signoff"])
def test_every_part_of_the_review_opens_for_a_signed_in_person_and_for_nobody(tab):
    world, thread, _ = fresh()
    for person in (None, SAM):
        assert (
            world.client(person).get(run_path(thread, "review"), params={"tab": tab}).status_code
            == 200
        )


def test_a_disagreement_is_drawn_as_rejected_in_the_picture_and_in_the_finished_brief():
    world, thread, request = fresh()
    record_all(world, thread)
    decide(world, thread, request, tx="TX-1003", outcome="reject", reason="Not her.")
    page = world.client().get(run_path(thread, "review"))
    assert marks(page, "rejected") == 1 and marks(page, "decided") == 5
    world.client().post(
        run_path(thread, "sign"),
        data={"brief_digest": request.brief_digest, "outcome": "returned", "reason": "Again."},
    )
    finished = world.client().get(run_path(thread, "signed"))
    assert marks(finished, "rejected") == 1 and marks(finished, "decided") == 5
