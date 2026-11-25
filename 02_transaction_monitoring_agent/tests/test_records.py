"""The topic's fact kinds and copied attributes."""

import pytest
from pydantic import ValidationError

from fsi_common.records import CheckResult, Extractor, Fact
from utils.records import (
    COPIED_ATTRIBUTES,
    FACT_CONTEXT,
    FACT_KINDS,
    TRANSACTION_SCHEME,
    transaction_anchor,
)


def test_the_topic_declares_two_kinds_of_fact():
    assert FACT_KINDS == ("transaction_assessment", "customer_attribute")


def test_the_copied_attributes_are_the_fields_of_the_transaction_row():
    assert COPIED_ATTRIBUTES == (
        "user_id",
        "timestamp",
        "merchant",
        "category",
        "amount",
        "currency",
        "country",
        "channel",
    )


def test_a_transaction_has_the_anchor_tx_and_its_id():
    assert TRANSACTION_SCHEME == "tx"
    assert transaction_anchor("TX-1003") == "tx:TX-1003"


def _fact(**changes):
    base = {
        "context": FACT_CONTEXT,
        "kind": "transaction_assessment",
        "subject": {"source_id": "source:" + "a" * 16, "anchor": "tx:TX-1003"},
        "quote": '"user_id": "USR-001"',
        "attributes": {"user_id": "USR-001", "risk_score": 45, "reason": "Unusual."},
        "status": {"status": "observed", "observed_at": "2026-11-25"},
        "provenance": {
            "source_id": "source:" + "a" * 16,
            "anchor": "tx:TX-1003",
            "extractor": Extractor(name="x", version="1"),
            "model": "claude-sonnet-5-5",
            "prompt_version": "assessor-1",
            "as_of": "sha256:" + "0" * 64,
        },
        "checks": [CheckResult(check="c.v1", outcome="pass", detail="found")],
    }
    return Fact.build(**{**base, **changes})


def test_the_score_and_the_reason_stay_out_of_the_id_and_a_copied_field_goes_in():
    first = _fact()
    reworded = _fact(attributes={"user_id": "USR-001", "risk_score": 80, "reason": "Different."})
    other_user = _fact(attributes={"user_id": "USR-002", "risk_score": 45, "reason": "Unusual."})
    assert first.id == reworded.id
    assert first.id != other_user.id


def test_a_kind_outside_the_list_is_refused():
    with pytest.raises(ValidationError, match="transaction_alert"):
        _fact(kind="transaction_alert")
