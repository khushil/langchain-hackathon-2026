"""Tests of the unit accounting: every unit read ends with facts or with a recorded reason."""

import pytest
from context.accounting import (
    NO_FACT_REASON,
    TABLE_NO_FACT_REASON,
    account_for_units,
    no_fact_reason,
)
from context.errors import AccountingError
from context.reader import read_document
from context.tables import read_tables

from fsi_common.records import CheckResult, Fact
from utils.records import FACT_CONTEXT

DOCUMENT = read_document("PS26-4")
SECTION7_UNITS = [u for u in DOCUMENT.units if u.anchor.startswith("para:7.")]


def _fact(anchor: str) -> Fact:
    return Fact.build(
        context=FACT_CONTEXT,
        kind="obligation",
        subject={"source_id": DOCUMENT.source.id, "anchor": anchor},
        quote=f"quote for {anchor}",
        attributes={"requirement": ["r"], "deadline": None},
        status={"status": "documented"},
        provenance={
            "source_id": DOCUMENT.source.id,
            "anchor": anchor,
            "extractor": {"name": "x", "version": "1"},
            "as_of": DOCUMENT.source.digest,
        },
        checks=[CheckResult(check="quote-verbatim.v1", outcome="pass", detail="ok")],
    )


def test_account_for_units_closes_when_every_unit_has_facts_or_a_reason():
    facts = [_fact("para:7.1"), _fact("para:7.2"), _fact("para:7.3"), _fact("para:7.5")]
    result = account_for_units(DOCUMENT.source, SECTION7_UNITS, SECTION7_UNITS, facts)
    accounting = result.accounting
    assert accounting.units_in == 5
    assert accounting.with_facts == ["para:7.1", "para:7.2", "para:7.3", "para:7.5"]
    assert [u.anchor for u in accounting.without_facts] == ["para:7.4"]
    assert accounting.without_facts[0].reason == NO_FACT_REASON
    assert result.line == "PS26-4: 5 of 5 units accounted for (4 with facts, 1 without)"
    assert result.phantom_anchors == []


def test_account_for_units_with_no_facts_gives_every_unit_a_reason():
    result = account_for_units(DOCUMENT.source, SECTION7_UNITS, SECTION7_UNITS, [])
    assert result.accounting.with_facts == []
    assert len(result.accounting.without_facts) == 5
    assert result.line.endswith("(0 with facts, 5 without)")


def test_account_for_units_fails_naming_a_unit_that_was_read_and_is_missing():
    held = [u for u in SECTION7_UNITS if u.anchor != "para:7.4"]
    with pytest.raises(AccountingError, match=r"para:7\.4") as caught:
        account_for_units(DOCUMENT.source, SECTION7_UNITS, held, [_fact("para:7.1")])
    assert caught.value.missing == ["para:7.4"]
    assert "4 of 5" in str(caught.value)


def test_account_for_units_fails_naming_every_missing_unit():
    held = SECTION7_UNITS[:2]
    with pytest.raises(AccountingError) as caught:
        account_for_units(DOCUMENT.source, SECTION7_UNITS, held, [])
    assert caught.value.missing == ["para:7.3", "para:7.4", "para:7.5"]


def test_account_for_units_fails_on_a_unit_the_source_was_never_read_into():
    extra = [u for u in DOCUMENT.units if u.anchor == "para:8.1"]
    with pytest.raises(AccountingError, match=r"para:8\.1") as caught:
        account_for_units(DOCUMENT.source, SECTION7_UNITS, SECTION7_UNITS + extra, [])
    assert caught.value.unexpected == ["para:8.1"]


def test_account_for_units_names_facts_on_a_unit_that_does_not_exist_and_does_not_count_them():
    facts = [_fact("para:7.1"), _fact("para:7.9")]
    result = account_for_units(DOCUMENT.source, SECTION7_UNITS, SECTION7_UNITS, facts)
    assert result.phantom_anchors == ["para:7.9"]
    assert result.accounting.with_facts == ["para:7.1"]
    assert result.accounting.units_in == 5


def test_account_for_units_ignores_facts_of_another_source():
    other = read_tables("FIRM-001")
    result = account_for_units(DOCUMENT.source, SECTION7_UNITS, SECTION7_UNITS, other.facts)
    assert result.accounting.with_facts == []
    assert result.phantom_anchors == []


def test_account_for_units_of_a_source_read_into_nothing_fails():
    with pytest.raises(AccountingError, match="no units"):
        account_for_units(DOCUMENT.source, [], [], [])


def test_a_table_source_gets_its_own_reason_for_a_row_with_no_fact():
    tables = read_tables("FIRM-001")
    firms = next(s for s in tables.sources if s.key == "firms")
    assert no_fact_reason(DOCUMENT.source) == NO_FACT_REASON
    assert no_fact_reason(firms) == TABLE_NO_FACT_REASON
    assert "paragraph" not in TABLE_NO_FACT_REASON and "section reader" not in TABLE_NO_FACT_REASON
    rows = [u for u in tables.units if u.source_id == firms.id]
    result = account_for_units(firms, rows, rows, [], reason=no_fact_reason(firms))
    assert {u.reason for u in result.accounting.without_facts} == {TABLE_NO_FACT_REASON}
