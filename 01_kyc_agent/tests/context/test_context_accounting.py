"""Every application and screening is accounted for, or the run stops naming what is missing."""

import pytest

from context.accounting import account_for_units
from context.errors import AccountingError
from context.reader import read_applications, read_screenings


def facts_on(anchors, source):
    from fsi_common.records import Fact
    from utils.records import FACT_CONTEXT

    return [
        Fact.build(
            context=FACT_CONTEXT,
            kind="screening",
            subject={"source_id": source.id, "anchor": a},
            quote="x",
            attributes={"list": "sanctions"},
            status={"status": "documented"},
            provenance={
                "source_id": source.id,
                "anchor": a,
                "extractor": {"name": "t", "version": "1"},
                "as_of": source.digest,
            },
            checks=[{"check": "quote-verbatim.v1", "outcome": "pass", "detail": "ok"}],
        )
        for a in anchors
    ]


@pytest.fixture()
def screenings():
    return read_screenings()


def test_350_screenings_close_when_each_has_a_fact_or_a_reason(screenings):
    anchors = [u.anchor for u in screenings.units]
    with_facts = anchors[:14]
    reasons = {a: f"No likeness: score 0.3{i % 10}" for i, a in enumerate(anchors[14:])}
    result = account_for_units(
        screenings.source,
        screenings.units,
        screenings.units,
        facts_on(with_facts, screenings.source),
        reasons=reasons,
    )
    accounting = result.accounting
    assert (accounting.units_in, len(accounting.with_facts), len(accounting.without_facts)) == (
        350,
        14,
        336,
    )
    assert result.line == "screenings: 350 of 350 units accounted for (14 with facts, 336 without)"


def test_a_screening_with_no_fact_and_no_reason_stops_the_run_by_name(screenings):
    anchors = [u.anchor for u in screenings.units]
    reasons = {a: "No likeness: score 0.30" for a in anchors[1:]}
    with pytest.raises(AccountingError, match=anchors[0]):
        account_for_units(
            screenings.source, screenings.units, screenings.units, [], reasons=reasons
        )


def test_a_dropped_screening_stops_the_run_naming_it(screenings):
    held = [u for u in screenings.units if u.anchor != "pair:CUST-010/pep-3"]
    with pytest.raises(AccountingError, match="pair:CUST-010/pep-3") as caught:
        account_for_units(screenings.source, screenings.units, held, [])
    assert caught.value.missing == ["pair:CUST-010/pep-3"]


def test_a_unit_held_that_was_never_read_stops_the_run(screenings):
    applications = read_applications()
    with pytest.raises(AccountingError, match="never read"):
        account_for_units(
            screenings.source, screenings.units, [*screenings.units, applications.units[0]], []
        )


def test_every_application_is_accounted_for_with_facts():
    apps = read_applications()
    anchors = [u.anchor for u in apps.units]
    result = account_for_units(
        apps.source,
        apps.units,
        apps.units,
        facts_on(anchors, apps.source),
    )
    assert result.line == "applications: 25 of 25 units accounted for (25 with facts, 0 without)"
    assert result.phantom_anchors == []


def test_a_fact_on_a_unit_that_was_never_read_is_named_as_a_phantom():
    apps = read_applications(["CUST-001"])
    result = account_for_units(
        apps.source, apps.units, apps.units, facts_on(["row:CUST-001", "row:CUST-099"], apps.source)
    )
    assert result.phantom_anchors == ["row:CUST-099"]


def test_a_source_read_into_no_units_is_refused():
    apps = read_applications()
    with pytest.raises(AccountingError, match="no units"):
        account_for_units(apps.source, [], [], [])
