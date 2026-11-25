"""The starter's 25 labels, carried unchanged into a data file, and the loader that reads them."""

import hashlib

import pytest

from evals import labels as lb
from utils import db


def test_there_are_25_labels_one_for_each_application():
    labels = lb.read_labels()
    assert [x.customer_id for x in labels] == [r["customer_id"] for r in db.table("applications")]
    assert len(labels) == 25


def test_the_distribution_is_the_starters_13_high_and_12_low():
    labels = lb.read_labels()
    assert sum(x.risk_level == "high" for x in labels) == 13
    assert sum(x.risk_level == "low" for x in labels) == 12


def test_the_expected_decision_is_derived_as_the_starter_derives_it():
    by_id = {x.customer_id: x for x in lb.read_labels()}
    assert by_id["CUST-002"].decision == "reject"
    assert by_id["CUST-001"].decision == "approve"
    assert all(
        x.decision == ("reject" if x.risk_level == "high" else "approve") for x in by_id.values()
    )


def test_three_labels_are_edge_cases_and_they_are_the_starters_three():
    edge = [x.customer_id for x in lb.read_labels() if x.edge_case]
    assert edge == ["CUST-015", "CUST-018", "CUST-021"]
    reasons = {x.customer_id: x.reason for x in lb.read_labels()}
    assert reasons["CUST-018"] == (
        "Edge case: same name as a sanctioned person but a different date of birth"
    )


def test_a_label_is_carried_as_the_starter_wrote_it():
    by_id = {x.customer_id: x for x in lb.read_labels()}
    assert (by_id["CUST-015"].risk_level, by_id["CUST-015"].reason) == (
        "high",
        "Edge case: spouse of a senior official (PEP relative), not on any list",
    )
    assert (by_id["CUST-025"].risk_level, by_id["CUST-025"].reason) == (
        "high",
        "Sanctioned: exact name and date of birth match",
    )


def test_the_file_names_its_source_and_says_the_labels_are_the_starters():
    head = [
        line for line in lb.LABELS_PATH.read_text(encoding="utf-8").splitlines() if line[:1] == "#"
    ]
    text = " ".join(head)
    assert "01_kyc_agent/scripts/run_experiments.py" in text
    assert "lines 51 to 77" in text
    assert "12acee0" in text
    assert "starter" in text.lower()


def test_the_digest_on_record_is_the_files():
    assert lb.LABELS_SHA256 == hashlib.sha256(lb.LABELS_PATH.read_bytes()).hexdigest()
    assert lb.sha256_of(lb.LABELS_PATH) == lb.LABELS_SHA256


def test_a_wrong_header_is_refused(tmp_path):
    bad = tmp_path / "labels.tsv"
    bad.write_text("customer\trisk\n", encoding="utf-8")
    with pytest.raises(lb.LabelFormatError, match="header"):
        lb.read_labels(bad)


def test_a_short_row_is_refused_naming_it(tmp_path):
    lines = lb.LABELS_PATH.read_text(encoding="utf-8").splitlines()
    head = [line for line in lines if line[:1] == "#"]
    header = next(line for line in lines if line.startswith("customer_id"))
    bad = tmp_path / "labels.tsv"
    bad.write_text("\n".join([*head, header, "CUST-001\tlow"]) + "\n", encoding="utf-8")
    with pytest.raises(lb.LabelFormatError, match="CUST-001"):
        lb.read_labels(bad)


def test_a_level_that_is_not_low_or_high_is_refused(tmp_path):
    text = lb.LABELS_PATH.read_text(encoding="utf-8").replace("CUST-001\tlow", "CUST-001\tmedium")
    bad = tmp_path / "labels.tsv"
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(lb.LabelFormatError, match="medium"):
        lb.read_labels(bad)


def test_labels_that_miss_an_application_are_refused_naming_it(tmp_path):
    lines = [
        line
        for line in lb.LABELS_PATH.read_text(encoding="utf-8").splitlines()
        if not line.startswith("CUST-007\t")
    ]
    bad = tmp_path / "labels.tsv"
    bad.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(lb.LabelFormatError, match="CUST-007"):
        lb.read_labels(bad)


def test_a_label_for_no_application_is_refused_naming_it(tmp_path):
    text = lb.LABELS_PATH.read_text(encoding="utf-8") + "CUST-026\tlow\tNot an application\n"
    bad = tmp_path / "labels.tsv"
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(lb.LabelFormatError, match="CUST-026"):
        lb.read_labels(bad)


def test_a_label_changed_by_one_word_changes_the_digest(tmp_path):
    text = lb.LABELS_PATH.read_text(encoding="utf-8").replace("Clean customer", "Clean client", 1)
    bad = tmp_path / "labels.tsv"
    bad.write_text(text, encoding="utf-8")
    assert lb.sha256_of(bad) != lb.LABELS_SHA256
