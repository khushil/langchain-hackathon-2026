"""The scripted reader is faithful to the applications: its names and dates are theirs."""

import pytest
from kyc_fakes import NAMES, application_text, reading_of

from context.checks import check_date, check_name, check_quote
from utils import db


def test_the_names_cover_the_twenty_five_applications():
    assert sorted(NAMES) == sorted(r["customer_id"] for r in db.table("applications"))


@pytest.mark.parametrize("customer_id", sorted(NAMES))
def test_every_scripted_detail_passes_its_checks(customer_id):
    reading = reading_of(customer_id)
    text = application_text(customer_id)
    anchor = f"row:{customer_id}"
    assert check_name(reading.full_name.value, text, anchor=anchor).outcome == "pass"
    for detail in (
        reading.full_name,
        reading.date_of_birth,
        reading.nationality,
        reading.occupation,
        reading.source_of_funds,
        reading.funds_amount,
    ):
        assert check_quote(detail.quote, text, anchor=anchor).outcome == "pass"
    dob = reading.date_of_birth
    assert check_date(dob.quote, dob.value, anchor=anchor).outcome == "pass"
