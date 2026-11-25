"""The start page, the list of runs and the page of a run that is still being assessed."""

import csv as csv_module
import io
import threading

import pytest
from engine_fakes import ScriptedModels
from review_support import WINDOW, make_world, marks, run_path, start_run, text, wait_for

from review_app.context import PREFIX


def test_the_start_page_with_no_run_says_so_and_offers_each_customer():
    world = make_world()
    page = world.client().get(f"{PREFIX}/")
    assert page.status_code == 200
    assert "No customer has been assessed yet. Choose a customer to start." in text(page)
    assert "Priya Shah" in page.text and "Tomás Ferreira" in page.text
    assert 'name="start"' in page.text and 'name="end"' in page.text


def test_a_signed_in_person_starts_a_run_and_lands_on_its_page():
    world = make_world()
    response = world.client().post(f"{PREFIX}/runs", data={"user_id": "USR-001", **WINDOW})
    assert response.status_code == 303
    thread = response.headers["location"].rsplit("/", 1)[1]
    assert response.headers["location"] == run_path(thread)
    wait_for(world.runs, thread, {"awaiting_review"})
    assert world.client().get(run_path(thread)).headers["location"] == run_path(thread, "review")


def test_nobody_signed_in_cannot_start_a_run_and_is_told_why():
    world = make_world()
    response = world.client(None).post(f"{PREFIX}/runs", data={"user_id": "USR-001"})
    assert response.status_code == 403
    assert "Sign in with your name and role to start a run." in text(response)
    assert world.runs.list_runs() == []


@pytest.mark.parametrize(
    ("form", "words"),
    [
        ({"user_id": "USR-404"}, "Choose a customer."),
        ({"user_id": ""}, "Choose a customer."),
        (
            {"user_id": "USR-001", "start": "2026-10-19", "end": "2026-10-08"},
            "The day to start from must be before the day to stop at.",
        ),
        (
            {"user_id": "USR-001", "start": "2026-10-19", "end": "2026-10-19"},
            "The day to start from must be before the day to stop at.",
        ),
        ({"user_id": "USR-002", "start": "2026-11-01"}, "no transaction in that window"),
    ],
)
def test_a_request_that_cannot_run_is_refused_in_words_and_no_run_starts(form, words):
    world = make_world()
    response = world.client().post(f"{PREFIX}/runs", data=form)
    assert response.status_code == 422
    assert words in text(response)
    assert world.runs.list_runs() == []


def test_a_second_run_while_one_is_assessed_is_refused_in_words():
    gate = threading.Event()
    world = make_world(ScriptedModels(hold=gate))
    first = world.client().post(f"{PREFIX}/runs", data={"user_id": "USR-001", **WINDOW})
    assert first.status_code == 303
    second = world.client().post(f"{PREFIX}/runs", data={"user_id": "USR-002"})
    assert second.status_code == 409
    assert "A run is still being assessed. Start another when it has finished." in text(second)
    gate.set()
    wait_for(world.runs, world.runs.list_runs()[0], {"awaiting_review"})


def test_a_run_being_assessed_refreshes_itself_and_says_how_many_transactions():
    gate = threading.Event()
    world = make_world(ScriptedModels(hold=gate))
    response = world.client().post(f"{PREFIX}/runs", data={"user_id": "USR-001", **WINDOW})
    page = world.client().get(response.headers["location"])
    assert page.status_code == 200
    assert 'http-equiv="refresh"' in page.text
    assert "Priya Shah's 6 transactions are being assessed." in text(page)
    assert 'data-hook="stream-count"' in page.text
    gate.set()
    wait_for(world.runs, world.runs.list_runs()[0], {"awaiting_review"})


def test_a_failed_run_says_in_words_that_it_stopped_and_why_and_does_not_refresh():
    world = make_world(ScriptedModels(fail=("TX-1003",)))
    response = world.client().post(f"{PREFIX}/runs", data={"user_id": "USR-001", **WINDOW})
    thread = response.headers["location"].rsplit("/", 1)[1]
    wait_for(world.runs, thread, {"failed"})
    page = world.client().get(run_path(thread))
    assert "The run for Priya Shah stopped before it was finished." in text(page)
    assert 'data-hook="run-error"' in page.text
    assert "The model call for TX-1003 failed" in text(page)
    assert 'http-equiv="refresh"' not in page.text


def test_the_runs_table_lists_each_run_newest_first_and_exports_what_it_shows():
    world = make_world()
    first = start_run(world, "USR-001", **WINDOW)
    second = start_run(world, "USR-002")
    page = world.client().get(f"{PREFIX}/")
    assert "2 runs so far: 2 waiting for a reviewer." in text(page)
    table = page.text[page.text.index('data-hook="table"') :]
    assert table.index(second) < table.index(first)
    csv = world.client().get(f"{PREFIX}/runs.csv")
    rows = list(csv_module.reader(io.StringIO(csv.text)))
    assert rows[0] == ["Run", "Transactions", "Status", "Reviewed by"]
    assert rows[1] == ["Tomás Ferreira, whole stream", "5", "Waiting for a reviewer", "Not yet"]
    assert rows[2] == [
        "Priya Shah, before 19 October 2026",
        "6",
        "Waiting for a reviewer",
        "Not yet",
    ]
    assert csv.headers["content-type"].startswith("text/csv")


def test_the_runs_table_sorts_by_a_column_and_the_export_follows_the_same_order():
    world = make_world()
    start_run(world, "USR-001", **WINDOW)
    start_run(world, "USR-002")
    for direction, wanted in (("asc", ["5", "6"]), ("desc", ["6", "5"])):
        body = world.client().get(f"{PREFIX}/runs.csv?sort=transactions&dir={direction}").text
        assert [row[1] for row in list(csv_module.reader(io.StringIO(body)))[1:]] == wanted


def test_the_start_page_picture_marks_all_fifteen_transactions_of_both_customers():
    world = make_world()
    page = world.client().get(f"{PREFIX}/")
    assert "15 of 15 transactions marked" in text(page)
    assert page.text.count('data-hook="mark"') == 15
    assert marks(page, "idle") == 15


def test_a_transaction_a_run_covers_is_marked_by_the_state_of_that_run_and_opens_it():
    world = make_world()
    thread = start_run(world, "USR-001", **WINDOW)
    page = world.client().get(f"{PREFIX}/")
    assert marks(page, "needs") == 6
    assert marks(page, "idle") == 9
    assert f"{run_path(thread, 'review')}?tx=TX-1003" in page.text


def test_an_unknown_run_is_a_page_that_says_so():
    world = make_world()
    page = world.client().get(run_path("nope"))
    assert page.status_code == 404
    assert "There is no run nope." in text(page)
