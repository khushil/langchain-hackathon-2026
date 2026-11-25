"""The starter's experiments script, carried: it imports with no key, uses the carried labels file
and its six evaluators behave as the starter wrote them."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import run_experiments as script

from evals.labels import read_labels

TOPIC = Path(__file__).resolve().parent.parent


def test_it_imports_with_no_langsmith_project_and_makes_no_call():
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("LANGSMITH_", "LANGCHAIN_"))
    } | {"LANGSMITH_PROJECT": "", "LANGSMITH_TRACING": "false", "PYTHONDONTWRITEBYTECODE": "1"}
    env["PYTHONPATH"] = os.pathsep.join([str(TOPIC.parent / "fsi_common"), str(TOPIC)])
    result = subprocess.run(
        [sys.executable, "-c", "import scripts.run_experiments as s; print(callable(s.main))"],
        cwd=TOPIC,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_run_as_a_script_it_stops_without_a_project(monkeypatch):
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.setattr(sys, "argv", ["run_experiments.py"])
    with pytest.raises(SystemExit, match="LANGSMITH_PROJECT is not set"):
        script.main()


def test_the_labels_are_the_carried_file_in_the_starters_shape():
    assert script.LABELS == {x.customer_id: (x.risk_level, x.reason) for x in read_labels()}
    assert len(script.LABELS) == 25
    source = Path(script.__file__).read_text(encoding="utf-8")
    assert "read_labels" in source and '"CUST-001": (' not in source


def test_the_dataset_examples_are_the_starters_shape():
    examples = script._build_dataset_examples()
    assert len(examples) == 25
    one = next(e for e in examples if e["inputs"]["customer_id"] == "CUST-018")
    assert set(one["outputs"]) == {"risk_level", "decision", "application", "label_reason"}
    assert one["outputs"]["decision"] == "approve"
    assert one["metadata"] == {"customer_id": "CUST-018", "edge_case": True}


def test_the_expected_decision_is_the_starters():
    assert script.expected_decision("high") == "reject"
    assert script.expected_decision("low") == "approve"


REF = {"risk_level": "high", "decision": "reject", "application": "I am Viktor Harlan."}


def score(evaluator, outputs, reference=REF):
    return evaluator(outputs, reference)["score"]


def test_risk_level_and_decision_correct():
    assert score(script.risk_level_correct, {"risk_level": "high"}) is True
    assert score(script.risk_level_correct, {"risk_level": "low"}) is False
    assert score(script.decision_correct, {"decision": "reject"}) is True
    assert score(script.decision_correct, {}) is False


def test_false_negative_is_a_high_risk_customer_waved_through():
    assert score(script.false_negative, {"risk_level": "low"}) is True
    assert score(script.false_negative, {"risk_level": "high"}) is False
    low = {**REF, "risk_level": "low"}
    assert score(script.false_negative, {"risk_level": "low"}, low) is False


def test_false_positive_is_a_low_risk_customer_sent_to_a_human():
    low = {**REF, "risk_level": "low", "decision": "approve"}
    assert score(script.false_positive, {"risk_level": "high"}, low) is True
    assert score(script.false_positive, {"risk_level": "low"}, low) is False
    assert score(script.false_positive, {"risk_level": "high"}) is False


def test_profile_extracted_needs_the_name_in_the_application_and_a_ten_character_date():
    good = {"profile": {"full_name": "Viktor Harlan", "date_of_birth": "1968-07-02"}}
    assert score(script.profile_extracted, good) is True
    other = {"profile": {"full_name": "Victor Harlan", "date_of_birth": "1968-07-02"}}
    assert score(script.profile_extracted, other) is False
    short = {"profile": {"full_name": "Viktor Harlan", "date_of_birth": "2 July 1968"}}
    assert score(script.profile_extracted, short) is False
    assert score(script.profile_extracted, {}) is False


def test_memo_consistent_needs_the_name_the_decision_and_at_most_150_words():
    outputs = {
        "profile": {"full_name": "Viktor Harlan"},
        "decision_memo": "Viktor Harlan is a PEP. We reject the application.",
    }
    assert score(script.memo_consistent, outputs) is True
    assert (
        score(script.memo_consistent, {**outputs, "decision_memo": "Viktor Harlan. approve"})
        is False
    )
    assert (
        score(
            script.memo_consistent,
            {**outputs, "decision_memo": "x " * 151 + "Viktor Harlan reject"},
        )
        is False
    )
    assert score(script.memo_consistent, {"decision_memo": "reject"}) is False


def test_the_evaluators_are_the_starters_six():
    assert [f.__name__ for f in script.EVALUATORS] == [
        "risk_level_correct",
        "decision_correct",
        "false_negative",
        "false_positive",
        "profile_extracted",
        "memo_consistent",
    ]
