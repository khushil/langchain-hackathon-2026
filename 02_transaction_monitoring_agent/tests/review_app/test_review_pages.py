"""The review page: the answer, the picture, each transaction opened beside its source."""

import html

import pytest
from engine_fakes import ScriptedModels, label_script
from review_support import WINDOW, make_world, marks, run_path, start_run, text

from review_app.context import PREFIX


@pytest.fixture(scope="module")
def waiting():
    world = make_world()
    thread = start_run(world, "USR-001", **WINDOW)
    return world, thread


def review(world, thread, client=None, **query):
    client = client or world.client()
    return client.get(run_path(thread, "review"), params=query)


def test_the_page_opens_on_one_sentence_and_three_tiles_built_from_the_same_counts(waiting):
    world, thread = waiting
    page = review(world, thread)
    assert page.status_code == 200
    words = text(page)
    assert (
        "The brief for Priya Shah has 6 transactions to decide. 6 still need your decision before "
        "it can be signed."
    ) in words
    assert page.text.count('data-hook="tile"') == 3
    assert "0 of 6" in words and "0 of 0" in words


def test_the_picture_marks_all_six_transactions_and_each_opens_its_transaction(waiting):
    world, thread = waiting
    page = review(world, thread)
    assert "6 of 6 transactions marked" in text(page)
    assert page.text.count('data-hook="mark"') == 6
    for tx_id in ("TX-1001", "TX-1002", "TX-1003", "TX-1004", "TX-1005", "TX-1006"):
        assert f"?tx={tx_id}" in page.text
    assert marks(page, "needs") == 6


def test_the_brief_lists_a_statement_for_each_transaction_with_its_state(waiting):
    world, thread = waiting
    page = review(world, thread)
    assert page.text.count('data-hook="statement"') == 6
    assert "TX-1003 at Hotel Miramar Lisboa, 380.0 GBP in PT (online): proposed approve" in text(
        page
    )
    assert "9 October 2026" in text(page)


def test_the_first_transaction_that_needs_a_decision_is_open_by_default_with_its_source(waiting):
    world, thread = waiting
    page = review(world, thread)
    words = text(page)
    assert "TX-1001, FreshMart Express" in words
    assert 'data-hook="source-line"' in page.text and "<mark>" in page.text
    assert "Proposed decision Approve" in words


def test_a_transaction_chosen_in_the_address_shows_its_assessment_checks_and_why_confidence_fell(
    waiting,
):
    world, thread = waiting
    words = text(review(world, thread, tx="TX-1003"))
    assert "TX-1003, Hotel Miramar Lisboa" in words
    assert "9 October 2026, 21:03" in words
    assert "Risk score 45 of 100" in words
    assert "Confidence 0.5, lowered from 0.9" in words
    assert "Risk score 45 is in the grey zone (30-69)" in words
    assert "Customer's home country GB" in words and "Customer's usual spend 10 to 150 GBP" in words
    assert words.count("Passed") >= 6
    assert "The proposed decision follows the score, blocking from 70" in words


def test_the_quote_is_marked_in_the_transactions_line_and_its_digest_is_given(waiting):
    world, thread = waiting
    page = review(world, thread, tx="TX-1005")
    line = html.unescape(page.text[page.text.index('data-hook="source-line"') :].split("</p>")[0])
    assert '{"transaction_id": "TX-1005", <mark>"user_id": "USR-001"' in line
    assert '"channel": "online"</mark>}' in line
    assert "Table digest" in text(page) and "sha256:" in page.text


def test_a_signed_in_person_sees_the_decision_form_and_nobody_else_does(waiting):
    world, thread = waiting
    signed_in = review(world, thread)
    assert 'data-hook="decision-form"' in signed_in.text
    assert 'name="outcome"' in signed_in.text and 'name="final"' in signed_in.text
    nobody = review(world, thread, world.client(None))
    assert 'data-hook="decision-form"' not in nobody.text
    assert "to decide on this transaction." in text(nobody)


def test_no_page_of_the_run_explains_the_method_or_carries_a_caveat(waiting):
    world, thread = waiting
    for tab in ("brief", "questions", "history", "signoff"):
        words = text(review(world, thread, tab=tab)).lower()
        for banned in ("how this is worked out", "not legal", "regulatory advice", "caveat"):
            assert banned not in words


def test_the_questions_tab_with_no_question_says_so_and_the_history_tab_with_no_history_says_so(
    waiting,
):
    world, thread = waiting
    assert "The brief carries no open questions." in text(review(world, thread, tab="questions"))
    history = review(world, thread, tab="history")
    assert "No decision about Priya Shah has been recorded before." in text(history)
    assert 'data-hook="export"' in history.text


def test_the_sign_off_tab_says_why_the_brief_cannot_be_signed_and_disables_the_button(waiting):
    world, thread = waiting
    page = review(world, thread, tab="signoff")
    assert "The brief cannot be signed yet: 6 transactions without a decision." in text(page)
    assert "disabled" in page.text.split('name="outcome" value="signed"')[1].split(">")[0]


def test_a_run_that_is_not_waiting_sends_the_review_address_to_its_own_page():
    world = make_world()
    response = world.client().post(f"{PREFIX}/runs", data={"user_id": "USR-001", **WINDOW})
    thread = response.headers["location"].rsplit("/", 1)[1]
    from review_support import wait_for

    wait_for(world.runs, thread, {"awaiting_review"})
    assert review(world, "nope").status_code == 404


def test_a_transaction_with_no_usable_assessment_is_marked_asked_about_and_opens_its_question():
    world = make_world(ScriptedModels(label_script() | {"TX-1002": None}))
    thread = start_run(world, "USR-001", **WINDOW)
    page = review(world, thread, tx="TX-1002")
    words = text(page)
    assert marks(page, "question") == 1 and marks(page, "needs") == 5
    assert "TX-1002, City Transit" in words
    assert "The assessor left nothing usable for this transaction" in words
    assert "TX-1002 at City Transit, 7.4 GBP in GB: no usable assessment" in words
    assert 'data-hook="decision-form"' not in page.text
    questions = text(review(world, thread, tab="questions"))
    assert "No assessment was recorded for TX-1002 (City Transit, 7.4 GBP in GB)." in questions
    assert "Ask: Fraud analyst. Priority: high." in questions
