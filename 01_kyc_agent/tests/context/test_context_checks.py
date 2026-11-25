"""The plain-code checks: each passes on the true case and fails on a planted fault."""

import pytest

from context.checks import (
    AMOUNT_CHECK,
    DATE_CHECK,
    DOB_CHECK,
    NAME_CHECK,
    QUOTE_CHECK,
    SCORE_CHECK,
    check_amount,
    check_date,
    check_dob_comparison,
    check_name,
    check_quote,
    check_score,
)

TEXT = (
    "Hello. Name: Dmitri Volkonsky. Born 11 September 1975. "
    "I expect to deposit $2,000,000 from business."
)


def test_a_quote_in_the_application_passes():
    result = check_quote("Born 11 September 1975", TEXT, anchor="row:CUST-003")
    assert (result.check, result.outcome) == (QUOTE_CHECK, "pass")


@pytest.mark.parametrize(
    "quote", ["Born 11 September 1976", "born 11 September 1975", "Dmitri Volkonsk", ""]
)
def test_a_quote_that_is_not_the_applications_words_fails(quote):
    assert check_quote(quote, TEXT, anchor="row:CUST-003").outcome == "fail"


def test_a_name_must_be_written_in_the_application():
    assert check_name("Dmitri Volkonsky", TEXT, anchor="row:CUST-003").outcome == "pass"
    failed = check_name("Dmitry Volkonskiy", TEXT, anchor="row:CUST-003")
    assert (failed.check, failed.outcome) == (NAME_CHECK, "fail")
    assert "Dmitry Volkonskiy" in failed.detail


@pytest.mark.parametrize(
    ("quote", "value", "outcome"),
    [
        ("11 September 1975", "1975-09-11", "pass"),
        ("September 11, 1975", "1975-09-11", "pass"),
        ("1975-09-11", "1975-09-11", "pass"),
        ("11 September 1975", "1975-11-09", "fail"),
        ("11 September 1975", "11 September 1975", "fail"),
        ("Septembre 1975", "1975-09-11", "fail"),
        ("31 February 1975", "1975-02-31", "fail"),
    ],
)
def test_the_date_must_read_as_the_quote_says(quote, value, outcome):
    result = check_date(quote, value, anchor="row:CUST-003")
    assert (result.check, result.outcome) == (DATE_CHECK, outcome)


def test_an_amount_must_be_written_in_the_application():
    assert check_amount("$2,000,000", TEXT, anchor="row:CUST-003").outcome == "pass"
    result = check_amount("$20,000,000", TEXT, anchor="row:CUST-003")
    assert (result.check, result.outcome) == (AMOUNT_CHECK, "fail")


def test_a_score_is_recomputed_by_the_starters_measure():
    ok = check_score("Dmitri Volkonsky", "Dmitry Volkonskiy", "0.91")
    assert (ok.check, ok.outcome) == (SCORE_CHECK, "pass")
    assert check_score("Dmitri Volkonsky", "Dmitry Volkonskiy", "0.95").outcome == "fail"
    assert check_score("Dmitri Volkonsky", "Dmitry Volkonskiy", "not a number").outcome == "fail"


@pytest.mark.parametrize(
    ("applicant", "entry", "stated", "outcome"),
    [
        ("1975-09-11", "1975-09-11", True, "pass"),
        ("1996-03-14", "1985-08-07", False, "pass"),
        ("1996-03-14", "1985-08-07", True, "fail"),
        ("1975-09-11", "1975-09-11", False, "fail"),
        (None, "1985-08-07", None, "pass"),
        ("1996-03-14", None, None, "pass"),
        (None, "1985-08-07", True, "fail"),
    ],
)
def test_the_comparison_of_dates_of_birth_is_recomputed(applicant, entry, stated, outcome):
    result = check_dob_comparison(applicant, entry, stated)
    assert (result.check, result.outcome) == (DOB_CHECK, outcome)
