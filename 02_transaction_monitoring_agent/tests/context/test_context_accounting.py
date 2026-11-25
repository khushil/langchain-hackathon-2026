"""Every unit ends with a fact or a reason, and a run whose counts do not close stops by name."""

import pytest

from context.accounting import NO_ASSESSMENT_REASON, account_for_units
from context.checks import RecordedAssessment
from context.errors import AccountingError
from context.facts import assessment_fact, customer_facts
from context.reader import read_stream
from tools.decisions import _confidence_checks
from utils import db

STREAM = read_stream("USR-001", end="2026-10-09T00:00")  # TX-1001 and TX-1002


def facts_for(*ids):
    out = []
    for tx_id in ids:
        row = db.get("transactions", transaction_id=tx_id)
        recorded = RecordedAssessment(
            transaction_id=tx_id,
            risk_score=5,
            model_confidence=0.9,
            confidence=0.9,
            confidence_checks=_confidence_checks(5, row, "USR-001", (30, 70)),
            agent_decision="approve",
            reason="A small payment at home.",
        )
        out.append(
            assessment_fact(
                STREAM, row, recorded, model="m", prompt_version="p-1", observed_on="2026-11-25"
            )
        )
    return out


def units_of(source):
    return [u for u in STREAM.units if u.source_id == source.id]


def test_every_transaction_with_a_fact_and_the_profile_with_its_facts_close_at_2_of_2_and_1_of_1():
    transactions, profiles = STREAM.sources
    facts = facts_for("TX-1001", "TX-1002") + customer_facts(STREAM)
    one = account_for_units(transactions, units_of(transactions), units_of(transactions), facts)
    two = account_for_units(profiles, units_of(profiles), units_of(profiles), facts)
    assert one.phantom_anchors == [] and two.phantom_anchors == []
    assert one.accounting.units_in == 2
    assert one.accounting.with_facts == ["tx:TX-1001", "tx:TX-1002"]
    assert one.accounting.without_facts == []
    assert one.line == "transactions: 2 of 2 units accounted for (2 with facts, 0 without)"
    assert two.line == "customer_profiles: 1 of 1 units accounted for (1 with facts, 0 without)"


def test_a_transaction_with_no_assessment_is_listed_with_its_reason_and_the_counts_still_close():
    transactions, _ = STREAM.sources
    result = account_for_units(
        transactions,
        units_of(transactions),
        units_of(transactions),
        facts_for("TX-1001"),
        reason=NO_ASSESSMENT_REASON,
    )
    assert result.accounting.with_facts == ["tx:TX-1001"]
    assert [(u.anchor, u.reason) for u in result.accounting.without_facts] == [
        ("tx:TX-1002", NO_ASSESSMENT_REASON)
    ]
    assert result.line.endswith("2 of 2 units accounted for (1 with facts, 1 without)")


def test_a_dropped_transaction_stops_the_run_and_names_it():
    transactions, _ = STREAM.sources
    kept = [u for u in units_of(transactions) if u.anchor != "tx:TX-1002"]
    with pytest.raises(AccountingError, match=r"1 of 2 are held.*tx:TX-1002") as caught:
        account_for_units(transactions, units_of(transactions), kept, facts_for("TX-1001"))
    assert caught.value.missing == ["tx:TX-1002"]


def test_a_unit_held_that_was_never_read_stops_the_run_and_names_it():
    transactions, _ = STREAM.sources
    stranger = read_stream("USR-002").unit_of["tx:TX-2001"]
    held = [*units_of(transactions), stranger]
    with pytest.raises(AccountingError, match="never read.*tx:TX-2001") as caught:
        account_for_units(transactions, units_of(transactions), held, facts_for("TX-1001"))
    assert caught.value.unexpected == ["tx:TX-2001"]


def test_a_source_read_into_no_units_stops_the_run():
    transactions, _ = STREAM.sources
    with pytest.raises(AccountingError, match="no units"):
        account_for_units(transactions, [], [], [])


def test_facts_on_a_unit_that_is_not_read_are_named_and_not_counted():
    transactions, _ = STREAM.sources
    outsider = read_stream("USR-002")
    row = db.get("transactions", transaction_id="TX-2001")
    recorded = RecordedAssessment("TX-2001", 5, 0.9, 0.9, [], "approve", "Small.")
    stray = assessment_fact(
        outsider, row, recorded, model="m", prompt_version="p-1", observed_on="2026-11-25"
    )
    result = account_for_units(
        transactions, units_of(transactions), units_of(transactions), [*facts_for("TX-1001"), stray]
    )
    assert result.phantom_anchors == ["tx:TX-2001"]
    assert result.accounting.with_facts == ["tx:TX-1001"]


def test_a_reason_given_for_one_anchor_replaces_the_default_for_that_unit_only():
    transactions, _ = STREAM.sources
    result = account_for_units(
        transactions,
        units_of(transactions),
        units_of(transactions),
        [],
        reason="no fact",
        reasons={"tx:TX-1002": "special"},
    )
    assert {u.anchor: u.reason for u in result.accounting.without_facts} == {
        "tx:TX-1001": "no fact",
        "tx:TX-1002": "special",
    }
