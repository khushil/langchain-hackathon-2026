"""The service seam and the shared helpers of the pages."""

import pytest
from starlette.exceptions import HTTPException
from support import make_services, new_runs, start_run

from review_app import service
from review_app.context import (
    PREFIX,
    plain_error,
    read_run,
    run_tabs,
    run_url,
    runs_of,
    state_unavailable,
)


def test_addresses_are_built_in_one_place():
    assert PREFIX == "/kyc"
    assert run_url("t") == "/kyc/runs/t"
    assert run_url("t", "applications", "CUST-001") == "/kyc/runs/t/applications/CUST-001"
    assert run_url("t", "review", tab="", fact="x y") == "/kyc/runs/t/review?fact=x+y"


def test_a_run_is_read_with_its_status_and_the_customers_asked_for():
    runs = new_runs()
    thread = start_run(runs, ["CUST-003", "CUST-001"])
    info = read_run(make_services(runs), thread)
    assert (info.status, info.customers) == ("awaiting_review", ("CUST-003", "CUST-001"))
    assert info.label == "2 applications"
    assert read_run(make_services(runs), start_run(runs)).label == "All 25 applications"


def test_a_run_the_engine_does_not_know_is_a_404_in_words():
    with pytest.raises(HTTPException) as caught:
        read_run(make_services(new_runs()), "none")
    assert caught.value.status_code == 404 and "There is no run none." in caught.value.detail


def test_an_engine_that_is_not_part_of_the_build_is_a_503_in_words():
    def missing():
        raise service.EngineMissingError("The engine is not part of this build.")

    with pytest.raises(HTTPException) as caught:
        runs_of(make_services(new_runs()).__class__(runs=missing))
    assert caught.value.status_code == 503


def test_an_engine_failure_is_said_without_a_hash_or_a_mode_name():
    assert plain_error(None) == "The engine gave no reason."
    assert "no saved answer" in plain_error("no recording for request 3f" + "a" * 40).lower()
    said = plain_error("stopped at sha256:" + "ab" * 32)
    assert "sha256" not in said and said.startswith("Stopped")


def test_a_state_folder_that_cannot_be_written_is_a_503_that_says_what_was_not_done():
    error = state_unavailable(OSError("disk full at /secret/path"), "Nothing was recorded")
    assert error.status_code == 503
    assert error.detail.startswith("Nothing was recorded.") and "/secret/path" not in error.detail


def test_tabs_differ_for_a_batch_waiting_and_one_finished():
    waiting = [key for key, _, _ in run_tabs("t", "awaiting_review")]
    done = [key for key, _, _ in run_tabs("t", "signed")]
    assert waiting == ["applications", "screenings", "signoff"]
    assert done == ["signed", "screenings"]


def test_a_run_of_every_application_is_named_from_the_table_and_not_from_a_number(monkeypatch):
    from review_app.context import RunInfo
    from utils import db

    def label(count):
        return RunInfo("t", "signed", tuple(f"CUST-{n:03d}" for n in range(count)), {}).label

    assert label(25) == "All 25 applications"
    monkeypatch.setattr(db, "table", lambda name: [{"customer_id": f"C{n}"} for n in range(3)])
    assert label(3) == "All 3 applications"
    assert label(25) == "25 applications"
    assert label(1) == "1 application"
