"""The start page, the list of runs and the page of a run that is being written or has stopped."""

from __future__ import annotations

import csv
import io
import re

import pytest
from review_fakes import FakeRuns, examples_review
from review_fixtures import make_client
from review_helpers import BASE, RUN, settle_everything

from review_app.service import (
    DocumentNotFoundError,
    FirmNotFoundError,
    InvalidRequestError,
    RunNotFoundError,
    UnknownSectionError,
)


def test_start_page_says_what_is_waiting_and_lists_every_run(runs):
    runs.add(
        "run-2",
        "signed",
        review=examples_review(),
        request={"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "x", "sections": ["7"]},
    )
    page = make_client(runs).get(f"{BASE}/")
    assert "2 briefs so far: 1 waiting for a reviewer, 1 signed." in page.text
    assert page.text.count('data-hook="tile"') == 3
    assert "PS26-4 for Harbour Mutual Bank, section 7" in page.text
    assert page.text.count("<tr>") == 3


def test_start_page_with_no_runs_says_so_and_offers_every_section():
    page = make_client(FakeRuns()).get(f"{BASE}/")
    assert "No brief has been started." in page.text
    assert len(re.findall(r'name="sections"', page.text)) == 10
    assert "7. Incident reporting" in page.text


def test_the_runs_table_exports_the_rows_it_shows(runs):
    runs.add(
        "run-2", "failed", request={"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "x"}
    )
    c = make_client(runs)
    rows = list(csv.reader(io.StringIO(c.get(f"{BASE}/runs.csv?sort=status&dir=asc").text)))
    assert rows[0] == ["Brief", "Sections", "Status", "Reviewed by"]
    assert len(rows) == 3
    assert {r[2] for r in rows[1:]} == {"Waiting for a reviewer", "Stopped"}
    assert {r[3] for r in rows[1:]} == {"Not yet"}


def test_starting_a_brief_needs_a_signed_in_person_and_calls_nothing_without_one(runs):
    c = make_client(runs, signed_in=None)
    page = c.post(
        f"{BASE}/runs", data={"document_id": "PS26-4", "firm_id": "FIRM-001", "sections": ["7"]}
    )
    assert page.status_code == 403
    assert "Sign in with your name and role to start a brief." in page.text
    assert runs.started == []


def test_starting_a_brief_for_one_section_sends_the_section_filter():
    runs = FakeRuns()
    c = make_client(runs)
    done = c.post(
        f"{BASE}/runs", data={"document_id": "PS26-4", "firm_id": "FIRM-001", "sections": ["7"]}
    )
    assert (
        done.status_code == 303 and done.headers["location"] == f"{RUN.replace('run-1', 'run-1')}"
    )
    assert runs.started == [
        {
            "document_id": "PS26-4",
            "firm_id": "FIRM-001",
            "request": "Summarise document PS26-4 for FIRM-001",
            "sections": ["7"],
        }
    ]


def test_starting_a_brief_for_every_section_sends_no_filter():
    runs = FakeRuns()
    sections = [str(n) for n in range(1, 11)]
    make_client(runs).post(
        f"{BASE}/runs", data={"document_id": "PS26-4", "firm_id": "FIRM-001", "sections": sections}
    )
    assert "sections" not in runs.started[0]


@pytest.mark.parametrize(
    ("data", "words"),
    [
        ({"document_id": "PS26-4", "firm_id": "FIRM-001"}, "Choose at least one section."),
        (
            {"document_id": "PS26-4", "firm_id": "FIRM-001", "sections": ["11"]},
            "Choose at least one section.",
        ),
        (
            {"document_id": "NOPE", "firm_id": "FIRM-001", "sections": ["7"]},
            "Choose a document and a firm.",
        ),
        (
            {"document_id": "PS26-4", "firm_id": "FIRM-999", "sections": ["7"]},
            "Choose a document and a firm.",
        ),
    ],
)
def test_a_start_with_nothing_to_read_or_an_unknown_document_is_refused_in_words(data, words):
    runs = FakeRuns()
    page = make_client(runs).post(f"{BASE}/runs", data=data)
    assert page.status_code == 422 and words in page.text
    assert runs.started == []


def test_a_second_start_while_one_is_being_written_is_refused_in_words():
    runs = FakeRuns()
    c = make_client(runs)
    data = {"document_id": "PS26-4", "firm_id": "FIRM-001", "sections": ["7"]}
    c.post(f"{BASE}/runs", data=data)
    page = c.post(f"{BASE}/runs", data=data)
    assert page.status_code == 409
    assert "A brief is still being written." in page.text


def test_a_run_being_written_shows_its_progress_and_refreshes_itself():
    runs = FakeRuns()
    runs.add(
        "run-1",
        "running",
        request={
            "document_id": "PS26-4",
            "firm_id": "FIRM-001",
            "request": "x",
            "sections": ["6", "7"],
        },
        section_results={"6": {}},
    )
    page = make_client(runs).get(RUN)
    assert "is being written: 1 of 2 sections read." in page.text
    assert '<meta http-equiv="refresh"' in page.text
    assert "<td>Read</td>" in page.text and "<td>Waiting</td>" in page.text


def test_a_failed_run_says_what_stopped_it_and_does_not_refresh():
    runs = FakeRuns()
    runs.add(
        "run-1",
        "failed",
        error="Section 7 could not be read: the model gave no answer.",
        request={"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "x"},
    )
    page = make_client(runs).get(RUN)
    assert "stopped before it was finished" in page.text
    assert "Section 7 could not be read: the model gave no answer." in page.text
    assert "http-equiv" not in page.text


def test_a_run_waiting_for_review_leads_to_the_review_and_a_signed_run_to_its_record(runs):
    runs.add("run-2", "signed", review=examples_review())
    c = make_client(runs)
    assert c.get(RUN).headers["location"] == f"{RUN}/review"
    assert c.get(f"{BASE}/runs/run-2").headers["location"] == f"{BASE}/runs/run-2/signed"


def test_an_unknown_run_is_a_page_in_words(client):
    page = client.get(f"{BASE}/runs/nope/review")
    assert page.status_code == 404 and "There is no run nope." in page.text
    assert "There is nothing at this address." not in page.text


def _ticked(html: str) -> list[str]:
    boxes = re.findall(r'<input type="checkbox" name="sections" value="(\d+)"( checked)?>', html)
    return [number for number, ticked in boxes if ticked]


def test_the_start_form_ticks_every_section_when_it_is_first_opened():
    page = make_client(FakeRuns()).get(f"{BASE}/")
    assert _ticked(page.text) == [str(n) for n in range(1, 11)]


def test_after_a_refused_start_only_the_sections_that_were_posted_are_ticked():
    runs = FakeRuns()
    c = make_client(runs)
    page = c.post(
        f"{BASE}/runs",
        data={"document_id": "PS26-4", "firm_id": "FIRM-999", "sections": ["6", "7"]},
    )
    assert page.status_code == 422
    assert _ticked(page.text) == ["6", "7"]
    nothing = c.post(f"{BASE}/runs", data={"document_id": "PS26-4", "firm_id": "FIRM-001"})
    assert nothing.status_code == 422 and "Choose at least one section." in nothing.text
    assert _ticked(nothing.text) == []
    busy = make_client(runs)
    data = {"document_id": "PS26-4", "firm_id": "FIRM-001", "sections": ["3"]}
    busy.post(f"{BASE}/runs", data=data)
    again = busy.post(f"{BASE}/runs", data=data)
    assert again.status_code == 409 and _ticked(again.text) == ["3"]


@pytest.mark.parametrize(
    ("error", "words"),
    [
        (InvalidRequestError("The request lacks firm_id."), "The request lacks firm_id."),
        (DocumentNotFoundError("Document NOPE is not in the library."), "Document NOPE is not"),
        (FirmNotFoundError("Firm FIRM-404 is not in the firm table."), "Firm FIRM-404 is not"),
        (UnknownSectionError("Section 11 is not in the document."), "Section 11 is not"),
    ],
)
def test_a_start_the_engine_refuses_is_said_in_words_and_not_a_server_error(error, words):
    runs = FakeRuns()
    runs.raises["start"] = error
    page = make_client(runs).post(
        f"{BASE}/runs", data={"document_id": "PS26-4", "firm_id": "FIRM-001", "sections": ["7"]}
    )
    assert page.status_code == 422
    assert "The brief could not be started." in page.text and words in page.text
    assert runs.started == []


def test_a_run_that_has_gone_when_the_reviewer_submits_is_a_page_in_words(runs):
    c = make_client(runs)
    review = settle_everything(c, runs)
    runs.raises["submit"] = RunNotFoundError("There is no run run-1.")
    page = c.post(
        f"{RUN}/sign", data={"brief_digest": review.request.brief_digest, "outcome": "signed"}
    )
    assert page.status_code == 404
    assert "There is no run run-1." in page.text
    runs.raises.clear()
    runs.raises["review_request"] = RunNotFoundError("There is no run run-1.")
    assert c.get(f"{RUN}/review").status_code == 404
