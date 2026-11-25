"""Reading the stream: one unit for each transaction of the window and one for the customer."""

import json

import pytest

from context.errors import CustomerNotFoundError, EmptyStreamError
from context.reader import read_stream
from fsi_common.ids import digest_bytes, digest_text
from utils import PROJECT_ROOT
from utils.state import OCT_19

DATA = PROJECT_ROOT / "data"


def test_the_whole_stream_of_a_customer_is_read_in_time_order_one_unit_each():
    stream = read_stream("USR-001")
    assert [t["transaction_id"] for t in stream.transactions] == [
        "TX-1001",
        "TX-1002",
        "TX-1003",
        "TX-1004",
        "TX-1005",
        "TX-1006",
        "TX-1007",
        "TX-1008",
        "TX-1009",
        "TX-1010",
    ]
    anchors = [u.anchor for u in stream.units]
    assert anchors == [f"tx:{t['transaction_id']}" for t in stream.transactions] + [
        "customer:USR-001"
    ]
    assert len(stream.unit_text) == len(stream.units) == 11


def test_a_window_reads_from_the_start_up_to_but_not_including_the_end():
    before = read_stream("USR-001", end=OCT_19)
    after = read_stream("USR-001", start=OCT_19)
    assert len(before.transactions) == 6
    assert [t["transaction_id"] for t in after.transactions] == [
        "TX-1007",
        "TX-1008",
        "TX-1009",
        "TX-1010",
    ]
    assert read_stream("USR-002", end=OCT_19).transactions[-1]["transaction_id"] == "TX-2005"


def test_the_two_customers_streams_hold_all_15_transactions():
    both = [read_stream(u).transactions for u in ("USR-001", "USR-002")]
    assert sorted(t["transaction_id"] for stream in both for t in stream) == sorted(
        json.loads(line)["transaction_id"]
        for line in (DATA / "transactions.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert sum(len(s) for s in both) == 15


def test_each_unit_text_is_the_line_of_its_file_and_each_digest_is_of_that_line():
    stream = read_stream("USR-002")
    lines = (DATA / "transactions.jsonl").read_text(encoding="utf-8").splitlines()
    by_anchor = {u.anchor: u for u in stream.units}
    for t in stream.transactions:
        unit = by_anchor[f"tx:{t['transaction_id']}"]
        assert stream.unit_text[unit.id] in lines
        assert unit.text_digest == digest_text(stream.unit_text[unit.id])
    profile = by_anchor["customer:USR-002"]
    assert (
        stream.unit_text[profile.id]
        in (DATA / "customer_profiles.jsonl").read_text(encoding="utf-8").splitlines()
    )


def test_the_sources_are_the_two_tables_with_the_digests_of_their_bytes():
    stream = read_stream("USR-001")
    transactions, profiles = stream.sources
    assert (transactions.key, transactions.kind) == ("transactions", "table")
    assert transactions.digest == digest_bytes((DATA / "transactions.jsonl").read_bytes())
    assert profiles.digest == digest_bytes((DATA / "customer_profiles.jsonl").read_bytes())
    assert transactions.locator == "02_transaction_monitoring_agent/data/transactions.jsonl"
    assert "starter" in transactions.terms


def test_a_customer_who_is_not_in_the_table_is_refused_by_name():
    with pytest.raises(CustomerNotFoundError, match="USR-404"):
        read_stream("USR-404")


def test_a_window_with_no_transaction_is_refused_by_name():
    with pytest.raises(EmptyStreamError, match="USR-002.*2026-11-01"):
        read_stream("USR-002", start="2026-11-01")


def test_the_window_includes_its_start_and_excludes_its_end_to_the_minute():
    window = read_stream("USR-001", start="2026-10-09T21:03", end="2026-10-11T02:14")
    assert [t["transaction_id"] for t in window.transactions] == ["TX-1003", "TX-1004"]
