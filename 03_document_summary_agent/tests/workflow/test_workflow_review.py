"""Tests of the review step: sign-off, return, partial decisions, carry-over and refusals."""

import pytest
from engine_fakes import (
    REVIEW_DATE,
    Harness,
    ScriptedModels,
    bundle_records,
    default_summary,
    ghost_summary,
    respond,
)

from fsi_common.bundle_checks import check_bundle
from fsi_common.examples.data import REVIEWER
from fsi_common.records import Decision, Fact, OpenQuestion, SignOff
from utils.records import FACT_CONTEXT
from utils.state import ReviewMismatchError, decisions_namespace, sign_offs_namespace
from workflow.review import validate_response

FIRM, DOC = "FIRM-001", "PS26-4"


def test_the_run_stops_at_the_review_with_the_brief_and_every_fact_beside_its_paragraph():
    harness = Harness()
    config = harness.start("7")
    request = harness.review_request(config)
    assert harness.graph.get_state(config).next == ("review",)
    assert len(request.statements) == 2
    cited = [c for s in request.statements for c in s.facts]
    assert {c.carry.outcome for c in cited} == {"fresh"}
    obligation = next(c for c in cited if c.fact.kind == "obligation")
    assert obligation.fact.quote in obligation.unit_text
    values = harness.values(config)
    assert not values.get("sign_off") and not values.get("decisions")


def test_a_signed_review_stores_the_decisions_and_the_sign_off_and_ends_the_run():
    harness = Harness()
    config = harness.start("7")
    request = harness.review_request(config)
    harness.resume(config, respond(request))
    state = harness.graph.get_state(config)
    values = state.values
    assert state.next == ()
    assert values["sign_off"]["outcome"] == "signed"
    assert values["sign_off"]["brief_digest"] == request.brief_digest
    assert len(values["decisions"]) == 5
    stored = harness.store.search(decisions_namespace(FIRM, DOC), limit=100)
    assert sorted(i.key for i in stored) == sorted(values["decisions"])
    signed = harness.store.search(sign_offs_namespace(FIRM, DOC), limit=100)
    assert [i.key for i in signed] == [values["sign_off"]["id"]]


def test_a_returned_review_keeps_the_reason_and_ends_the_run():
    harness = Harness()
    config = harness.start("7")
    request = harness.review_request(config)
    harness.resume(config, respond(request, outcome="returned", decide="reject"))
    values = harness.values(config)
    assert values["sign_off"]["outcome"] == "returned"
    assert values["sign_off"]["reason"] == "Returned for a rewrite."
    assert {d["outcome"] for d in values["decisions"].values()} == {"reject"}


def test_decisions_without_a_sign_off_are_kept_and_the_run_waits_for_the_reviewer_again():
    harness = Harness()
    config = harness.start("7")
    request = harness.review_request(config)
    partial = respond(request).model_copy(update={"sign_off": None})
    harness.resume(config, partial)
    state = harness.graph.get_state(config)
    assert state.next == ("review",)
    assert len(state.values["decisions"]) == 5
    again = harness.review_request(config)
    assert {c.carry.outcome for s in again.statements for c in s.facts} == {"carried"}
    harness.resume(config, respond(again))
    assert harness.values(config)["sign_off"]["outcome"] == "signed"


def test_a_rerun_on_the_same_firm_and_document_carries_the_earlier_decisions():
    harness = Harness()
    first = harness.start("7")
    harness.resume(first, respond(harness.review_request(first)))
    second = harness.start("7")
    request = harness.review_request(second)
    carried = [c for s in request.statements for c in s.facts]
    assert {c.carry.outcome for c in carried} == {"carried"}
    assert {c.carry.decision.reviewer.name for c in carried} == {REVIEWER["name"]}
    assert {c.carry.decision.date for c in carried} == {REVIEW_DATE}
    harness.resume(second, respond(request))
    values = harness.values(second)
    assert len(values["decisions"]) == 5
    assert values["sign_off"]["outcome"] == "signed"


def test_a_decision_on_a_fact_that_also_has_a_carried_decision_replaces_it_in_the_run():
    harness = Harness()
    first = harness.start("7")
    harness.resume(first, respond(harness.review_request(first)))
    second = harness.start("7")
    request = harness.review_request(second)
    target = request.statements[0].facts[0]
    assert target.carry.outcome == "carried"
    sam = {"name": "Sam Okoye", "role": "Compliance Officer"}
    amend = Decision.on(
        target.fact,
        outcome="amend",
        reason="Checked against the paragraph.",
        reviewer=sam,
        date="2026-11-26",
        amendment="Reworded.",
    )
    response = respond(request, reviewer=sam)
    harness.resume(second, response.model_copy(update={"decisions": [amend]}))
    values = harness.values(second)
    on_target = [d for d in values["decisions"].values() if d["subject_id"] == target.fact.id]
    assert [(d["outcome"], d["reviewer"]["name"]) for d in on_target] == [("amend", "Sam Okoye")]
    others = [d for d in values["decisions"].values() if d["subject_id"] != target.fact.id]
    assert {d["reviewer"]["name"] for d in others} == {REVIEWER["name"]}
    assert len(values["decisions"]) == 5
    assert check_bundle(bundle_records(values), where="state") == []


def test_a_response_that_decides_no_carried_fact_keeps_every_carried_decision():
    harness = Harness()
    first = harness.start("7")
    harness.resume(first, respond(harness.review_request(first)))
    second = harness.start("7")
    harness.resume(second, respond(harness.review_request(second)))
    values = harness.values(second)
    assert len(values["decisions"]) == 5
    assert {d["reviewer"]["name"] for d in values["decisions"].values()} == {REVIEWER["name"]}


def test_a_rerun_that_rewords_a_requirement_asks_again_with_the_difference_named():
    harness = Harness()
    first = harness.start("7")
    harness.resume(first, respond(harness.review_request(first)))

    def reworded(section):
        base = default_summary(section)
        moved = base.obligations[0].model_copy(update={"requirement": "Tell the FSOA at once"})
        return base.model_copy(update={"obligations": [moved, *base.obligations[1:]]})

    rerun = Harness(ScriptedModels(section=reworded), store=harness.store)
    second = rerun.start("7")
    cited = [c for s in rerun.review_request(second).statements for c in s.facts]
    asked = [c for c in cited if c.carry.outcome == "ask_again"]
    assert len(asked) == 1
    assert asked[0].carry.differences == ["attributes.requirement"]
    assert asked[0].carry.decision.reviewer.name == REVIEWER["name"]
    assert sorted(c.carry.outcome for c in cited).count("carried") == len(cited) - 1


def test_a_rerun_with_a_new_quote_is_a_fresh_fact_and_asks_without_an_earlier_decision():
    harness = Harness()
    first = harness.start("7")
    harness.resume(first, respond(harness.review_request(first)))

    def shorter(section):
        base = default_summary(section)
        moved = base.obligations[0].model_copy(update={"evidence": "Firms must submit an initial"})
        return base.model_copy(update={"obligations": [moved, *base.obligations[1:]]})

    rerun = Harness(ScriptedModels(section=shorter), store=harness.store)
    cited = [c for s in rerun.review_request(rerun.start("7")).statements for c in s.facts]
    assert sorted(c.carry.outcome for c in cited).count("fresh") == 1


def test_a_rerun_with_another_model_and_prompt_still_carries(monkeypatch):
    import workflow.sections as sections
    from utils.models import RoleModel

    harness = Harness()
    first = harness.start("7")
    harness.resume(first, respond(harness.review_request(first)))
    monkeypatch.setitem(sections.ROLE_MODELS, "section", RoleModel("claude-sonnet-9-9", "low", "x"))
    monkeypatch.setattr(sections, "SECTION_PROMPT_VERSION", "section-new")
    second = harness.start("7")
    cited = [c for s in harness.review_request(second).statements for c in s.facts]
    models = {c.fact.provenance.model for c in cited if c.fact.kind == "obligation"}
    assert models == {"claude-sonnet-9-9"}
    assert {c.carry.outcome for c in cited} == {"carried"}


def test_an_open_question_answered_in_the_review_moves_to_answered():
    def ghost(section):
        base = default_summary(section)
        extra = base.obligations[0].model_copy(update={"paragraph": "7.9"})
        return base.model_copy(update={"obligations": [*base.obligations, extra]})

    harness = Harness(ScriptedModels(section=ghost))
    config = harness.start("7")
    request = harness.review_request(config)
    question = request.open_questions[0]
    answer = Decision.on(
        question,
        outcome="answer",
        answer="It is paragraph 7.1.",
        reason="Read the paragraphs.",
        reviewer=REVIEWER,
        date=REVIEW_DATE,
    )
    response = respond(request)
    response = response.model_copy(update={"decisions": [*response.decisions, answer]})
    harness.resume(config, response)
    values = harness.values(config)
    settled = OpenQuestion.model_validate(values["open_questions"][question.id])
    assert (settled.state, settled.decision_id) == ("answered", answer.id)
    assert answer.id in values["decisions"]
    rerun = harness.start("7")
    again = harness.review_request(rerun).open_questions[0]
    assert (again.state, again.decision_id) == ("answered", answer.id)


def test_a_sign_off_for_another_digest_is_refused_before_anything_is_stored():
    harness = Harness()
    config = harness.start("7")
    request = harness.review_request(config)
    good = respond(request)
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
            good.model_copy(update={"sign_off": wrong}), request, harness.values(config)
        )


def test_a_decision_on_something_the_reviewer_was_not_shown_is_refused():
    harness = Harness()
    config = harness.start("7")
    request = harness.review_request(config)
    values = harness.values(config)
    other = next(
        Fact.model_validate(c[0], context=FACT_CONTEXT)
        for c in values["facts"].values()
        if Fact.model_validate(c[0], context=FACT_CONTEXT).subject.anchor == "row:PROVIDER-001"
    )
    stray = Decision.on(
        other, outcome="accept", reason="Looks right.", reviewer=REVIEWER, date=REVIEW_DATE
    )
    response = respond(request)
    response = response.model_copy(update={"decisions": [*response.decisions, stray]})
    with pytest.raises(ReviewMismatchError, match="was not shown"):
        validate_response(response, request, values)


def test_a_decision_on_a_changed_version_of_a_fact_is_refused():
    harness = Harness()
    config = harness.start("7")
    request = harness.review_request(config)
    values = harness.values(config)
    cited = request.statements[0].facts[0].fact
    stale = Decision.on(
        cited, outcome="accept", reason="Checked.", reviewer=REVIEWER, date=REVIEW_DATE
    ).model_copy(update={"seen_digest": "sha256:" + "1" * 64})
    response = respond(request, decide=None)
    response = response.model_copy(update={"decisions": [stale]})
    with pytest.raises(ReviewMismatchError, match="before it changed"):
        validate_response(response, request, values)


def _ghost_run():
    harness = Harness(ScriptedModels(section=ghost_summary))
    config = harness.start("7")
    return harness, config, harness.review_request(config)


def _signed_with(request, response, assumptions):
    sign_off = SignOff.build(
        brief_id=request.brief_id,
        brief_digest=request.brief_digest,
        reviewer=REVIEWER,
        date=REVIEW_DATE,
        outcome="signed",
        assumptions=assumptions,
    )
    return response.model_copy(update={"sign_off": sign_off})


def test_a_signed_sign_off_with_an_open_question_neither_answered_nor_accepted_is_refused():
    harness, config, request = _ghost_run()
    assert request.open_questions[0].state == "open"
    with pytest.raises(ReviewMismatchError, match=request.open_questions[0].id):
        validate_response(respond(request), request, harness.values(config))


def test_an_assumption_on_a_question_the_brief_does_not_carry_is_refused():
    harness = Harness()
    config = harness.start("7")
    request = harness.review_request(config)
    odd = _signed_with(
        request,
        respond(request),
        [{"question_id": "question:0000000000000000", "words": "Assume it."}],
    )
    with pytest.raises(ReviewMismatchError, match="question:0000000000000000"):
        validate_response(odd, request, harness.values(config))


def test_a_signed_sign_off_is_allowed_when_the_open_question_is_named_as_an_assumption():
    harness, config, request = _ghost_run()
    question = request.open_questions[0]
    response = _signed_with(
        request, respond(request), [{"question_id": question.id, "words": "Assume it is 7.1."}]
    )
    validate_response(response, request, harness.values(config))
    harness.resume(config, response)
    findings = check_bundle(bundle_records(harness.values(config)), where="state")
    assert [f for f in findings if f.check.startswith("signoff.")] == []


def test_a_signed_sign_off_is_allowed_when_the_question_is_answered_in_the_response():
    harness, config, request = _ghost_run()
    question = request.open_questions[0]
    answer = Decision.on(
        question,
        outcome="answer",
        answer="It is paragraph 7.1.",
        reason="Read the paragraphs.",
        reviewer=REVIEWER,
        date=REVIEW_DATE,
    )
    response = respond(request)
    response = response.model_copy(update={"decisions": [*response.decisions, answer]})
    validate_response(response, request, harness.values(config))


def test_a_returned_sign_off_needs_no_answer_to_an_open_question():
    harness, config, request = _ghost_run()
    validate_response(
        respond(request, outcome="returned", decide="reject"), request, harness.values(config)
    )


def test_the_state_after_a_clean_signed_run_passes_the_contracts_bundle_check():
    harness = Harness()
    config = harness.start("7")
    harness.resume(config, respond(harness.review_request(config)))
    assert check_bundle(bundle_records(harness.values(config)), where="state") == []


def test_a_signed_sign_off_is_allowed_when_an_earlier_answer_already_settled_the_question():
    harness, config, request = _ghost_run()
    answer = Decision.on(
        request.open_questions[0],
        outcome="answer",
        answer="It is paragraph 7.1.",
        reason="Read the paragraphs.",
        reviewer=REVIEWER,
        date=REVIEW_DATE,
    )
    first = respond(request)
    harness.resume(config, first.model_copy(update={"decisions": [*first.decisions, answer]}))
    rerun = harness.start("7")
    again = harness.review_request(rerun)
    assert again.open_questions[0].state == "answered"
    validate_response(respond(again), again, harness.values(rerun))


def test_a_fact_whose_paragraph_is_not_held_is_a_workflow_error_and_not_a_review_mismatch():
    from workflow.errors import WorkflowError
    from workflow.review import build_review_request

    harness = Harness()
    config = harness.start("7")
    values = dict(harness.values(config))
    values["units"] = {k: u for k, u in values["units"].items() if u["anchor"] != "para:7.1"}
    with pytest.raises(WorkflowError, match=r"para:7\.1") as caught:
        build_review_request(values, {})
    assert not isinstance(caught.value, ReviewMismatchError)


def test_a_question_answered_on_the_screen_still_signs_after_another_run_answered_it_first():
    harness = Harness(ScriptedModels(section=ghost_summary))
    waiting = harness.start("7")
    shown = harness.review_request(waiting).open_questions[0]
    other = harness.start("7")
    other_request = harness.review_request(other)
    first = Decision.on(
        other_request.open_questions[0],
        outcome="answer",
        answer="It is paragraph 7.1.",
        reason="Read the paragraphs.",
        reviewer=REVIEWER,
        date=REVIEW_DATE,
    )
    signed_first = respond(other_request)
    harness.resume(
        other, signed_first.model_copy(update={"decisions": [*signed_first.decisions, first]})
    )
    assert shown.state == "open"
    mine = Decision.on(
        shown,
        outcome="answer",
        answer="It is paragraph 7.2.",
        reason="Read them again.",
        reviewer=REVIEWER,
        date=REVIEW_DATE,
    )
    request = harness.review_request(waiting)
    response = respond(request)
    harness.resume(waiting, response.model_copy(update={"decisions": [*response.decisions, mine]}))
    values = harness.values(waiting)
    settled = OpenQuestion.model_validate(values["open_questions"][shown.id])
    assert (settled.state, settled.decision_id) == ("answered", mine.id)
    assert values["sign_off"]["outcome"] == "signed"


def test_a_decision_on_a_question_as_no_run_showed_it_is_still_refused():
    harness = Harness(ScriptedModels(section=ghost_summary))
    config = harness.start("7")
    request = harness.review_request(config)
    question = request.open_questions[0]
    unseen = OpenQuestion.model_validate(
        {**question.to_json(), "state": "answered", "decision_id": "decision:0123456789abcdef"}
    )
    stale = Decision.on(
        unseen,
        outcome="answer",
        answer="Paragraph 7.1.",
        reason="Read it.",
        reviewer=REVIEWER,
        date=REVIEW_DATE,
    )
    response = respond(request)
    response = response.model_copy(update={"decisions": [*response.decisions, stale]})
    with pytest.raises(ReviewMismatchError, match="before it changed"):
        validate_response(response, request, harness.values(config))
