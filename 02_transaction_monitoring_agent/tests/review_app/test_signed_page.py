"""The page of a finished brief: the sign-off record, the decisions and the stream as decided."""

import csv
import io

from engine_fakes import ScriptedModels, label_script
from review_support import WINDOW, make_world, marks, record_all, run_path, start_run, text


def signed(world, thread, outcome="signed", reason=""):
    request = world.runs.review_request(thread)
    body = {"brief_digest": request.brief_digest, "outcome": outcome}
    if reason:
        body["reason"] = reason
    response = world.client().post(run_path(thread, "sign"), data=body)
    assert response.status_code == 303, text(response)


def test_the_signed_page_says_who_signed_what_and_when_and_counts_the_decisions():
    world = make_world()
    thread = start_run(world, "USR-001", **WINDOW)
    record_all(world, thread)
    signed(world, thread)
    page = world.client().get(run_path(thread, "signed"))
    words = text(page)
    assert (
        "The brief for Priya Shah was signed by Dana Whitfield, Head of Compliance, on 25 "
        "November 2026."
    ) in words
    assert "6 of 6" in words
    assert 'data-hook="sign-off-record"' in page.text
    assert "Digest signed" in words and "sha256:" in page.text
    assert marks(page, "decided") == 6


def test_a_returned_brief_says_returned_and_gives_the_reason():
    world = make_world()
    thread = start_run(world, "USR-001", **WINDOW)
    signed(world, thread, "returned", "Assess them again with the hotel note.")
    words = text(world.client().get(run_path(thread, "signed")))
    assert "was returned by Dana Whitfield" in words
    assert "Reason for returning Assess them again with the hotel note." in words


def test_the_decisions_table_lists_each_transaction_with_what_was_proposed_and_decided():
    world = make_world()
    thread = start_run(world, "USR-001", **WINDOW)
    record_all(world, thread)
    request = world.runs.review_request(thread)
    third = next(c.fact for c in request.assessments if c.fact.subject.anchor == "tx:TX-1005")
    world.client().post(
        run_path(thread, "decide"),
        data={
            "brief_digest": request.brief_digest,
            "fact_id": third.id,
            "outcome": "amend",
            "final": "approve",
            "wording": "She bought it herself.",
            "reason": "She told me on the phone.",
        },
    )
    signed(world, thread)
    body = world.client().get(run_path(thread, "decisions.csv")).text
    rows = list(csv.reader(io.StringIO(body)))
    assert rows[0] == ["Transaction", "Proposed", "Decision", "Made by", "Date", "Reason"]
    by_tx = {row[0]: row for row in rows[1:]}
    assert len(by_tx) == 6
    assert by_tx["TX-1001"][1:3] == ["Approve", "Proposal agreed"]
    assert by_tx["TX-1005"][1:3] == ["Block", "Approve"]
    assert by_tx["TX-1005"][3] == "Dana Whitfield, Head of Compliance"
    assert by_tx["TX-1005"][5] == "She told me on the phone."


def test_a_transaction_opened_on_the_signed_page_shows_its_source_and_the_decision_on_it():
    world = make_world()
    thread = start_run(world, "USR-001", **WINDOW)
    record_all(world, thread)
    signed(world, thread)
    page = world.client().get(run_path(thread, "signed"), params={"tx": "TX-1003"})
    words = text(page)
    assert "TX-1003, Hotel Miramar Lisboa" in words
    assert "Agreed by you, on 25 November 2026." in words
    assert 'data-hook="source-line"' in page.text and "<mark>" in page.text
    assert 'data-hook="decision-form"' not in page.text


def test_a_question_answered_shows_in_the_table_and_the_picture():
    world = make_world(ScriptedModels(label_script() | {"TX-1002": None}))
    thread = start_run(world, "USR-001", **WINDOW)
    record_all(world, thread)
    request = world.runs.review_request(thread)
    world.client().post(
        run_path(thread, "answer"),
        data={
            "brief_digest": request.brief_digest,
            "question_id": request.open_questions[0].id,
            "final": "approve",
            "answer": "It is her usual commute.",
            "reason": "I rang her.",
        },
    )
    signed(world, thread)
    page = world.client().get(run_path(thread, "signed"))
    assert marks(page, "answered") == 1
    body = world.client().get(run_path(thread, "decisions.csv")).text
    row = next(r for r in csv.reader(io.StringIO(body)) if r[0] == "TX-1002")
    assert row[1:3] == ["No usable assessment", "Approve. It is her usual commute."]


def test_the_signed_page_of_a_run_still_waiting_leads_back_to_the_review():
    world = make_world()
    thread = start_run(world, "USR-001", **WINDOW)
    response = world.client().get(run_path(thread, "signed"))
    assert response.status_code == 303 and response.headers["location"] == run_path(thread)


def test_the_start_page_after_a_signed_run_names_the_reviewer_and_marks_the_transactions_decided():
    world = make_world()
    thread = start_run(world, "USR-001", **WINDOW)
    record_all(world, thread)
    signed(world, thread)
    page = world.client().get("/transaction-monitoring/")
    assert "1 run so far: 1 signed." in text(page)
    assert "Dana Whitfield, Head of Compliance, 25 November 2026" in text(page)
    assert marks(page, "decided") == 6
