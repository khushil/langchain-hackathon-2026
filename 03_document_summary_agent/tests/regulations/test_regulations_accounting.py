"""The units a reader gives must equal the units pinned for the fetched bytes."""

from __future__ import annotations

import copy
import dataclasses

import pytest
from regulation_fixtures import compose_act

from context.regulations.accounting import account_for_regulation, pin_record
from context.regulations.errors import DigestMismatchError, RegulationAccountingError
from context.regulations.official_journal import read_official_journal


def read(**kwargs):
    return read_official_journal(
        compose_act(**kwargs),
        key="SAMPLE",
        title="Sample",
        locator="https://example.org/a",
        terms="Not republished.",
    )


def without_unit(result, anchor: str):
    """Return the reading as a faulty reader would give it, with one unit dropped."""
    return dataclasses.replace(result, items=tuple(i for i in result.items if i.anchor != anchor))


def test_units_equal_to_the_pin_close_and_the_line_states_the_counts():
    result = read()
    outcome = account_for_regulation(result, pin_record(result))
    assert outcome.units_read == outcome.units_pinned == 22
    assert outcome.line == "SAMPLE: 22 of 22 units read and accounted for"
    assert outcome.by_kind["recital"] == 3


def test_a_unit_missing_from_the_read_is_named():
    pin = pin_record(read())
    with pytest.raises(RegulationAccountingError, match=r"1 of 22.*not read.*cit:2") as caught:
        account_for_regulation(without_unit(read(), "cit:2"), pin)
    assert caught.value.missing == ["cit:2"]


def test_a_unit_read_that_the_pin_does_not_hold_is_named():
    pin = copy.deepcopy(pin_record(read()))
    pin["units"] = [row for row in pin["units"] if row[0] != "cit:2"]
    with pytest.raises(RegulationAccountingError, match=r"cit:2") as caught:
        account_for_regulation(read(), pin)
    assert caught.value.unexpected == ["cit:2"]


def test_a_unit_whose_text_changed_is_named():
    pin = copy.deepcopy(pin_record(read()))
    pin["units"][2][2] = "sha256:" + "0" * 64
    with pytest.raises(RegulationAccountingError, match=r"changed.*rct:1") as caught:
        account_for_regulation(read(), pin)
    assert caught.value.changed == ["rct:1"]


def test_a_unit_listed_twice_in_the_pin_is_named():
    pin = copy.deepcopy(pin_record(read()))
    pin["units"].append(list(pin["units"][0]))
    with pytest.raises(RegulationAccountingError, match=r"twice.*cit:1") as caught:
        account_for_regulation(read(), pin)
    assert caught.value.repeated == ["cit:1"]


def test_a_pin_for_other_bytes_is_a_digest_mismatch_not_a_unit_difference():
    pin = copy.deepcopy(pin_record(read()))
    pin["source_digest"] = "sha256:" + "1" * 64
    with pytest.raises(DigestMismatchError, match="SAMPLE"):
        account_for_regulation(read(), pin)


def test_the_pin_holds_digests_and_anchors_and_no_text():
    pin = pin_record(read())
    assert set(pin) == {"key", "source_digest", "structure", "units_by_kind", "units"}
    flat = str(pin)
    assert "Operators need clear rules" not in flat
    assert all(len(row) == 3 and row[2].startswith("sha256:") for row in pin["units"])


def test_planted_a_unit_read_twice_is_named_by_the_accounting_not_only_by_counts():
    result = read()
    twice = dataclasses.replace(result, items=(*result.items, result.items[6]))
    with pytest.raises(RegulationAccountingError, match=r"twice.*art:1/2|art:1/2.*twice") as caught:
        account_for_regulation(twice, pin_record(result))
    assert caught.value.repeated == ["art:1/2"]
