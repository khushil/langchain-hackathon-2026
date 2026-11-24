"""The review model, the review route's builders, the source view, the library and the plug-in."""

from __future__ import annotations

from pathlib import Path

import pytest
from review_fakes import examples_review, section_seven_review
from review_fixtures import DANA, TODAY

from fsi_common.examples.data import build_examples
from fsi_common.records import Decision, Fact, Person, judged_digest, record_digest
from review_app import review_route
from review_app.drafts import Draft, DraftStore, person_key
from review_app.library import LibraryError, read_library
from review_app.review_model import ReviewModel
from review_app.review_route import ReviewInputError
from review_app.source_view import (
    NONE_STATED,
    anchor_label,
    attribute_value,
    check_label,
    decision_line,
    difference_label,
    mark_quote,
    unmapped_attribute_keys,
)
from utils.records import FACT_CONTEXT

TOPIC = Path(__file__).resolve().parents[2]
EX = build_examples()


def model_for(review, draft=None, *, viewer=DANA):
    return ReviewModel(
        review.request,
        draft or DraftStore().get("x", DANA),
        viewer=viewer,
        firm_name="Harbour Mutual Bank",
        document_title="PS26/4",
    )


def draft_with(*decisions):
    store = DraftStore()
    for d in decisions:
        store.put_fact_decision("x", d)
    return store.get("x", DANA)


def accept(fact, person=DANA):
    return Decision.on(fact, outcome="accept", reason="Matches.", reviewer=person, date=TODAY)


def test_mark_quote_finds_the_words_with_any_white_space_between_them():
    segments = mark_quote("7.1 Firms must\n  submit a report now.", "Firms must submit a report")
    assert [(s.text, s.marked) for s in segments] == [
        ("7.1 ", False),
        ("Firms must\n  submit a report", True),
        (" now.", False),
    ]


@pytest.mark.parametrize("quote", ["Firms must not submit", "", "   "])
def test_mark_quote_says_none_when_the_words_are_not_in_the_paragraph(quote):
    assert mark_quote("7.1 Firms must submit a report now.", quote) is None


def test_mark_quote_marks_the_first_place_when_the_words_occur_twice():
    segments = mark_quote("a b a b", "a b")
    assert [(s.text, s.marked) for s in segments] == [("a b", True), (" a b", False)]


def test_places_values_and_checks_are_named_in_words():
    assert anchor_label("para:7.1") == "Paragraph 7.1"
    assert anchor_label("row:FIRM-001") == "Row FIRM-001"
    assert attribute_value(None) == NONE_STATED
    assert attribute_value([]) == NONE_STATED
    assert attribute_value(["6.3", "9.1"]) == "6.3, 9.1"
    assert attribute_value(False) == "No" and attribute_value(True) == "Yes"
    check = EX.fact_7_1.checks[1]
    assert check_label(check) == "The deadline is word for word in the paragraph"
    assert difference_label("attributes.deadline") == "Deadline as written"
    assert difference_label("quote") == "The quoted words"
    assert difference_label("checks.deadline-verbatim.v1") == (
        "The deadline is word for word in the paragraph (result)"
    )


def test_every_attribute_key_of_the_example_and_section_seven_facts_has_a_label():
    facts = [EX.fact_7_1, EX.fact_9_3, EX.fact_notes, EX.fact_service, EX.fact_small_firm]
    facts += list(section_seven_review().facts.values())
    assert unmapped_attribute_keys(facts) == set()


def test_a_planted_attribute_key_with_no_label_is_reported():
    data = EX.fact_7_1.to_json()
    data["attributes"]["zzz_unlabelled"] = "x"
    fact = Fact.model_validate(data, context=FACT_CONTEXT)
    assert unmapped_attribute_keys([fact]) == {"zzz_unlabelled"}


def test_decision_line_names_the_person_the_outcome_and_the_date():
    assert decision_line(EX.accept_7_1) == (
        "Accepted by Dana Whitfield, Head of Compliance, on 25 November 2026"
    )


def test_the_answer_and_its_tiles_change_together_when_a_decision_is_added():
    review = examples_review()
    before = model_for(review).answer()
    after = model_for(review, draft_with(accept(EX.fact_7_1))).answer()
    assert "2 facts and 1 question still need your decision" in before.sentence
    assert "1 fact and 1 question still need your decision" in after.sentence
    assert before.tiles[1].value == "0 of 2" and after.tiles[1].value == "1 of 2"


def test_the_sentence_agrees_with_one_waiting_item_and_with_none():
    review = examples_review()
    store = DraftStore()
    store.put_fact_decision("x", accept(EX.fact_7_1))
    store.put_fact_decision("x", accept(EX.fact_9_3))
    store.put_assumption("x", DANA, review.question.id, "Assumed.")
    ready = model_for(review, store.get("x", DANA)).answer()
    assert ready.sentence.endswith(
        "Every fact and question is settled, so it is ready for you to sign."
    )
    store.put_assumption("x", DANA, review.question.id, "Assumed.")
    store._drafts[("x", person_key(DANA))].facts.pop(EX.fact_9_3.id)
    one = model_for(review, store.get("x", DANA)).answer()
    assert "1 fact still needs your decision before it can be signed." in one.sentence
    assert one.tiles[1].status == "needs_person" and one.tiles[2].status == "normal"


def test_a_rejection_blocks_signing_and_the_sentence_says_so():
    review = examples_review()
    store = DraftStore()
    store.put_fact_decision("x", accept(EX.fact_7_1))
    store.put_fact_decision(
        "x", Decision.on(EX.fact_9_3, outcome="reject", reason="No.", reviewer=DANA, date=TODAY)
    )
    store.put_assumption("x", DANA, review.question.id, "Assumed.")
    model = model_for(review, store.get("x", DANA))
    assert (
        "You rejected 1 fact, so the brief can be returned but not signed."
        in model.answer().sentence
    )
    assert "You rejected 1 fact that the brief cites." in model.cannot_sign_because()


def test_a_decision_on_a_fact_that_changed_is_not_counted():
    review = examples_review()
    stale = Decision.on(
        EX.fact_7_1_variant, outcome="accept", reason="Old.", reviewer=DANA, date=TODAY
    )
    model = model_for(review, draft_with(stale))
    assert [c.fact.id for c in model.facts_waiting] == [EX.fact_7_1.id, EX.fact_9_3.id]


def test_next_waiting_goes_on_from_the_current_fact_and_wraps_round():
    review = section_seven_review()
    ids = list(model_for(review).cited)
    model = model_for(review, draft_with(accept(review.facts[ids[1]])))
    assert model.next_waiting(ids[0]) == ids[2]
    assert model.next_waiting(ids[4]) == ids[0]
    everything = draft_with(*(accept(f) for f in review.facts.values()))
    assert model_for(review, everything).next_waiting(ids[0]) is None


def test_deciding_builds_a_decision_tied_to_the_fact_as_shown():
    review = examples_review()
    cited = review.request.statements[0].facts[0]
    decision = review_route.decide_fact(
        review.request,
        cited.fact.id,
        outcome="amend",
        reason="Reworded.",
        amendment="Within 4 hours.",
        person=DANA,
        on=TODAY,
    )
    assert decision.seen_digest == cited.seen_digest == record_digest(cited.fact)
    assert decision.judged_digest == judged_digest(cited.fact)
    assert (decision.reviewer, decision.date, decision.amendment) == (
        DANA,
        TODAY,
        "Within 4 hours.",
    )


@pytest.mark.parametrize("outcome", ["answer", "approve", "", "ACCEPT"])
def test_an_outcome_other_than_accept_amend_or_reject_is_refused_for_a_fact(outcome):
    review = examples_review()
    with pytest.raises(ReviewInputError, match="Choose accept, amend or reject"):
        review_route.decide_fact(
            review.request,
            EX.fact_7_1.id,
            outcome=outcome,
            reason="x",
            amendment=None,
            person=DANA,
            on=TODAY,
        )


def test_amend_without_wording_and_any_outcome_without_a_reason_are_refused():
    review = examples_review()
    kwargs = {"person": DANA, "on": TODAY}
    with pytest.raises(ReviewInputError, match="amended wording"):
        review_route.decide_fact(
            review.request, EX.fact_7_1.id, outcome="amend", reason="x", amendment=" ", **kwargs
        )
    with pytest.raises(ReviewInputError, match="your reason"):
        review_route.decide_fact(
            review.request, EX.fact_7_1.id, outcome="accept", reason=None, amendment=None, **kwargs
        )


def test_answering_builds_an_answer_decision_and_refuses_a_question_not_on_the_brief():
    review = examples_review()
    decision = review_route.answer_question(
        review.request,
        review.question.id,
        answer="Both in 2024.",
        reason="Register.",
        person=DANA,
        on=TODAY,
    )
    assert decision.outcome == "answer" and decision.subject_id == review.question.id
    with pytest.raises(ReviewInputError, match="not on this brief"):
        review_route.answer_question(
            review.request,
            "question:0000000000000000",
            answer="x",
            reason="y",
            person=DANA,
            on=TODAY,
        )
    with pytest.raises(ReviewInputError, match="not on this brief"):
        review_route.check_assumption(review.request, "question:0000000000000000", "x")


def test_the_response_carries_only_the_signed_in_persons_decisions_and_assumptions():
    review = examples_review()
    store = DraftStore()
    store.put_fact_decision("x", accept(EX.fact_7_1))
    store.put_fact_decision("x", accept(EX.fact_9_3))
    store.put_assumption("x", DANA, review.question.id, "Assumed.")
    draft = store.get("x", DANA)
    response = review_route.build_response(
        review.request,
        model_for(review, draft),
        draft,
        outcome="signed",
        reason=None,
        person=DANA,
        on=TODAY,
    )
    assert response.reviewer == DANA and len(response.decisions) == 2
    assert response.sign_off.brief_digest == review.request.brief_digest
    other = Person(name="Sam Okoye", role="Compliance Officer")
    with pytest.raises(ReviewInputError, match="made by Dana Whitfield, Head of Compliance"):
        review_route.build_response(
            review.request,
            model_for(review, draft),
            draft,
            outcome="signed",
            reason=None,
            person=other,
            on=TODAY,
        )


def test_the_draft_store_hands_out_copies_and_an_answer_replaces_an_assumption():
    store = DraftStore()
    store.put_assumption("t", DANA, "question:1", "words")
    held = store.get("t", DANA)
    held.assumptions.clear()
    assert store.get("t", DANA).assumptions == {"question:1": "words"}
    decision = review_route.answer_question(
        examples_review().request,
        examples_review().question.id,
        answer="a",
        reason="b",
        person=DANA,
        on=TODAY,
    )
    store.put_answer("t", decision)
    assert store.get("t", DANA).assumptions == {"question:1": "words"}
    store.put_assumption("t", DANA, decision.subject_id, "now assumed")
    assert decision.subject_id not in store.get("t", DANA).answers
    store.clear("t")
    assert store.get("t", DANA).answers == {} and store.get("t", DANA).assumptions == {}


def test_the_draft_store_keeps_each_persons_work_apart_and_gives_nobody_an_empty_draft():
    store = DraftStore()
    sam = Person(name="Sam Okoye", role="Compliance Officer")
    same_name_other_role = Person(name="Sam Okoye", role="Head of Compliance")
    store.put_fact_decision("t", accept(EX.fact_7_1, DANA))
    store.put_assumption("t", sam, "question:1", "Sam's words")
    assert set(store.get("t", DANA).facts) == {EX.fact_7_1.id}
    assert store.get("t", DANA).assumptions == {}
    assert store.get("t", sam).facts == {} and store.get("t", sam).assumptions
    assert store.get("t", same_name_other_role).assumptions == {}
    assert store.get("t", None).facts == {} and store.get("u", DANA).facts == {}
    store.clear("t")
    assert store.get("t", DANA).facts == {} and store.get("t", sam).assumptions == {}


def test_the_library_holds_the_document_with_ten_sections_and_the_firms():
    library = read_library(TOPIC / "data")
    document = library.document("PS26-4")
    assert document.title.startswith("Policy Statement PS26/4")
    assert [s.number for s in document.sections] == [str(n) for n in range(1, 11)]
    assert library.firm_name("FIRM-001") == "Harbour Mutual Bank"
    assert library.firm_name("FIRM-404") == "FIRM-404"
    assert library.document_title("NOPE") == "NOPE"


def test_a_library_with_a_missing_file_fails_loudly(tmp_path):
    with pytest.raises(LibraryError, match="documents.jsonl"):
        read_library(tmp_path)


def test_nothing_in_the_application_names_an_approve_control_or_the_models():
    for path in [
        *(TOPIC / "review_app").rglob("*"),
        *(TOPIC.parent / "fsi_common" / "fsi_common" / "app").rglob("*"),
    ]:
        if path.is_file() and path.suffix in {".py", ".html", ".css"}:
            text = path.read_text().lower()
            assert "approve" not in text, path
            assert "get_model" not in text and "make_chat_model" not in text, path


def test_the_plugin_loads_through_the_shell_from_the_topic_folder():
    from starlette.testclient import TestClient

    from fsi_common.app import create_app
    from fsi_common.app.topics import load_topic

    plugin = load_topic(TOPIC)
    assert (plugin.name, plugin.prefix) == ("compliance-brief", "/compliance-brief")
    app = create_app(topics=[plugin])
    about = TestClient(app).get("/about").text
    assert "PS26/4" in about and "Harbour Mutual Bank" in about


def test_the_run_service_is_the_one_given_and_the_missing_engine_is_said_in_words():
    from review_app import service

    fake = object()
    service.use_runs(fake)
    try:
        assert service.get_runs() is fake
    finally:
        service.use_runs(None)
    if service.BriefRuns is None:
        with pytest.raises(service.EngineMissingError, match="engine that writes briefs"):
            service.get_runs()


def test_a_build_without_the_engine_says_so_on_the_page_instead_of_failing():
    from starlette.testclient import TestClient

    from fsi_common.app import AppConfig, create_app
    from review_app import service
    from review_app.context import Services
    from review_app.plugin import build_plugin

    def missing():
        raise service.EngineMissingError("The engine that writes briefs is not part of this build.")

    app = create_app(
        AppConfig(secret=b"s", topic_folders=()), topics=[build_plugin(Services(runs=missing))]
    )
    page = TestClient(app).get("/compliance-brief/")
    assert page.status_code == 503
    assert "The engine that writes briefs is not part of this build." in page.text


def test_the_application_finds_this_topic_by_default():
    from fsi_common.app.config import REPOSITORY_ROOT, AppConfig, built_topic_folders

    assert TOPIC in built_topic_folders(REPOSITORY_ROOT)
    assert TOPIC in AppConfig.from_env({}).topic_folders


def test_a_held_decision_counts_as_the_viewers_only_when_the_viewer_made_it():
    review = examples_review()
    sam = Person(name="Sam Okoye", role="Compliance Officer")
    draft = Draft(facts={EX.fact_7_1.id: accept(EX.fact_7_1, sam)})  # as if handed over by mistake
    as_sam = model_for(review, draft, viewer=sam)
    assert as_sam.fact_states[EX.fact_7_1.id].kind == "yours"
    for viewer in (DANA, None):
        model = model_for(review, draft, viewer=viewer)
        assert model.fact_states[EX.fact_7_1.id].kind == "needs", viewer
        assert model.answer().tiles[1].value == "0 of 2"
