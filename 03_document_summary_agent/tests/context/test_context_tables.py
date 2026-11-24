"""Tests of reading the firm and provider tables into units and attribute facts."""

import pytest
from context.checks import QUOTE_CHECK
from context.errors import FirmNotFoundError
from context.tables import read_tables

from fsi_common.ids import digest_bytes, digest_text
from utils.db import DATA_DIR


def test_read_tables_gives_two_sources_and_a_unit_for_every_row():
    tables = read_tables("FIRM-001")
    assert [s.key for s in tables.sources] == ["firms", "third_party_providers"]
    assert [u.anchor for u in tables.units] == [
        "row:FIRM-001",
        "row:PROVIDER-001",
        "row:PROVIDER-002",
    ]
    firms = tables.sources[0]
    assert firms.digest == digest_bytes((DATA_DIR / "firms.jsonl").read_bytes())
    assert firms.kind == "table"
    assert len(tables.unit_text) == 3


def test_read_tables_unit_text_is_the_row_as_written_and_its_digest_is_of_that_text():
    tables = read_tables("FIRM-001")
    firm_unit = tables.units[0]
    text = tables.unit_text[firm_unit.id]
    assert text.startswith('{"firm_id": "FIRM-001"')
    assert firm_unit.text_digest == digest_text(text)


def test_read_tables_makes_firm_and_provider_facts_that_pass_their_quote_check():
    tables = read_tables("FIRM-001")
    kinds = sorted({f.kind for f in tables.facts})
    assert kinds == ["firm_attribute", "provider_attribute"]
    assert len(tables.facts) == 6 + 2 + 2 * 2
    for fact in tables.facts:
        assert fact.passed_checks, fact.id
        assert [c.check for c in fact.checks] == [QUOTE_CHECK]
        assert fact.status.status == "documented"
        assert fact.provenance.model is None


def test_read_tables_records_a_senior_manager_that_is_not_named_as_a_null_value():
    tables = read_tables("FIRM-001")
    fact = next(
        f
        for f in tables.facts
        if f.attributes.get("field") == "operational_resilience_senior_manager"
    )
    assert fact.attributes["value"] is None
    assert fact.quote == '"operational_resilience_senior_manager": null'


def test_read_tables_records_each_provider_link_with_its_own_text():
    tables = read_tables("FIRM-001")
    links = [f for f in tables.facts if f.attributes.get("field") == "provider_link"]
    assert [f.attributes["provider_id"] for f in links] == ["PROVIDER-001", "PROVIDER-002"]
    assert links[0].attributes["contract_end"] == "30 June 2027"
    assert links[0].attributes["material"] is True
    assert '"contract_end": "30 June 2027"' in links[0].quote
    assert links[0].quote != links[1].quote


def test_read_tables_twice_gives_identical_records():
    first, second = read_tables("FIRM-001"), read_tables("FIRM-001")
    assert [f.to_json() for f in first.facts] == [f.to_json() for f in second.facts]
    assert [u.to_json() for u in first.units] == [u.to_json() for u in second.units]


def test_read_tables_unknown_firm_is_named():
    with pytest.raises(FirmNotFoundError, match="FIRM-999"):
        read_tables("FIRM-999")
