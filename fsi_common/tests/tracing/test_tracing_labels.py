"""Tests for the labels every traced run carries: topic, institution, document and review."""

from __future__ import annotations

import pytest

from fsi_common.tracing import (
    TOPICS,
    UnknownTopicError,
    model_labels,
    resume_tags,
    run_labels,
)


def test_the_three_topics_are_named_once() -> None:
    assert sorted(TOPICS) == ["brief", "kyc", "monitoring"]
    assert TOPICS["kyc"].number == "01"
    assert TOPICS["monitoring"].number == "02"
    assert TOPICS["brief"].number == "03"
    assert TOPICS["brief"].label == "03-compliance-brief"


def test_a_run_carries_topic_institution_document_and_review() -> None:
    labels = run_labels(
        "brief",
        "thread-1",
        {"document_id": "PS26-4", "firm_id": "harbour", "document_digest": "abc123"},
    )
    assert labels.metadata["topic"] == "03-compliance-brief"
    assert labels.metadata["topic_number"] == "03"
    assert labels.metadata["institution"] == "harbour"
    assert labels.metadata["document_id"] == "PS26-4"
    assert labels.metadata["document_digest"] == "abc123"
    assert labels.metadata["thread_id"] == "thread-1"
    assert labels.metadata["review_id"] == "thread-1"
    assert set(labels.tags) == {
        "topic:03-compliance-brief",
        "institution:harbour",
        "document:PS26-4",
    }


def test_the_domain_keys_the_caller_gave_are_kept() -> None:
    labels = run_labels("kyc", "t", {"customers": 25, "applications_digest": "d"})
    assert labels.metadata["customers"] == 25
    assert labels.metadata["applications_digest"] == "d"
    assert "institution" not in labels.metadata
    assert "institution:" not in " ".join(labels.tags)


def test_labelling_a_labelled_run_changes_nothing() -> None:
    once = run_labels("brief", "t", {"document_id": "D", "firm_id": "F"})
    twice = run_labels("brief", "t", once.metadata)
    assert twice.metadata == once.metadata
    assert twice.tags == once.tags


def test_an_explicit_institution_wins_over_the_firm_key() -> None:
    labels = run_labels("brief", "t", {"firm_id": "F", "institution": "Other"})
    assert labels.metadata["institution"] == "Other"


def test_the_caller_is_not_changed() -> None:
    given = {"document_id": "D"}
    run_labels("brief", "t", given)
    assert given == {"document_id": "D"}


def test_an_unknown_topic_is_refused() -> None:
    with pytest.raises(UnknownTopicError):
        run_labels("payments", "t", {})
    with pytest.raises(UnknownTopicError):
        model_labels("payments", "section", model="m", effort=None)


def test_a_resumed_review_is_tagged_as_a_review_step() -> None:
    tags = resume_tags(["topic:03-compliance-brief"])
    assert tags == ["topic:03-compliance-brief", "stage:review"]
    assert resume_tags(tags) == tags


def test_a_model_call_carries_its_topic_and_role() -> None:
    labels = model_labels("kyc", "extract", model="claude-sonnet-5-5", effort="medium")
    assert labels.metadata == {
        "topic": "01-kyc-onboarding",
        "topic_number": "01",
        "model_role": "extract",
        "model_name": "claude-sonnet-5-5",
        "model_effort": "medium",
    }
    assert labels.tags == ["topic:01-kyc-onboarding", "role:extract"]


def test_a_model_without_an_effort_leaves_the_key_out() -> None:
    labels = model_labels("kyc", "extract", model="m", effort=None)
    assert "model_effort" not in labels.metadata
