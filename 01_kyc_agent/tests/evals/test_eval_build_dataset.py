"""The reference examples are built from the labels and the applications, byte for byte."""

import json

import pytest

from evals import build_dataset as bd
from evals import labels as lb
from utils import db


@pytest.fixture(scope="module")
def built():
    return bd.build()


def test_there_is_one_example_for_each_application_in_order(built):
    examples = [json.loads(line) for line in built.examples.splitlines()]
    assert [e["key"] for e in examples] == [r["customer_id"] for r in db.table("applications")]
    assert len(examples) == 25


def test_an_example_holds_the_label_the_application_and_the_edge_flag(built):
    example = json.loads(built.examples.splitlines()[17])
    assert example["inputs"] == {"customer_id": "CUST-018"}
    reference = example["reference_outputs"]
    assert reference["risk_level"] == "low" and reference["decision"] == "approve"
    assert reference["label_reason"].startswith("Edge case")
    assert reference["edge_case"] is True
    assert reference["application"].startswith("I'm Ivana Strahov")
    assert example["metadata"]["customer_id"] == "CUST-018"


def test_the_metadata_says_whose_labels_they_are(built):
    meta = json.loads(built.examples.splitlines()[0])["metadata"]
    assert meta["labels_sha256"] == "sha256:" + lb.LABELS_SHA256
    assert "starter" in meta["labels_made_by"]
    assert "run_experiments.py" in meta["labels_source"]
    assert "ours" not in meta["labels_made_by"].lower().split()


def test_the_reference_outputs_carry_what_the_starters_evaluators_read(built):
    for line in built.examples.splitlines():
        reference = json.loads(line)["reference_outputs"]
        assert {"risk_level", "decision", "application", "label_reason"} <= set(reference)


def test_two_builds_give_identical_bytes(built):
    assert bd.build().examples == built.examples


def test_the_file_on_disk_is_what_the_build_produces():
    assert bd.main(["--check"]) == 0


def test_check_fails_when_the_file_on_disk_differs(tmp_path, capsys):
    (tmp_path / "examples.jsonl").write_text(bd.build().examples + " ", encoding="utf-8")
    assert bd.main(["--check", "--out-dir", str(tmp_path)]) == 1
    assert "examples.jsonl on disk differs" in capsys.readouterr().out


def test_check_fails_when_the_file_is_missing(tmp_path, capsys):
    assert bd.main(["--check", "--out-dir", str(tmp_path)]) == 1
    assert "missing" in capsys.readouterr().out


def test_check_fails_when_the_labels_digest_is_not_the_one_on_record(tmp_path, capsys):
    text = lb.LABELS_PATH.read_text(encoding="utf-8").replace("Clean customer", "Clean client", 1)
    planted = tmp_path / "labels.tsv"
    planted.write_text(text, encoding="utf-8")
    assert bd.main(["--check", "--labels", str(planted)]) == 1
    assert "digest" in capsys.readouterr().out


def test_build_writes_the_file_and_reports_the_count(tmp_path, capsys):
    assert bd.main(["--out-dir", str(tmp_path)]) == 0
    assert len((tmp_path / "examples.jsonl").read_text(encoding="utf-8").splitlines()) == 25
    assert "built 25 of 25 applications" in capsys.readouterr().out


def test_labels_that_do_not_match_the_applications_stop_the_build(tmp_path, capsys):
    text = lb.LABELS_PATH.read_text(encoding="utf-8") + "CUST-026\tlow\tNot an application\n"
    planted = tmp_path / "labels.tsv"
    planted.write_text(text, encoding="utf-8")
    assert bd.main(["--check", "--labels", str(planted)]) == 1
    assert "CUST-026" in capsys.readouterr().out
