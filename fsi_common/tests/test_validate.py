"""Tests of the validator: its self-test, its exit codes, and its failure paths."""

import json
import shutil

import pytest

from fsi_common import validate
from fsi_common.checks import CHECKS, check_for_error
from fsi_common.examples.data import COPIED_ATTRIBUTES, FACT_KINDS


@pytest.fixture()
def topic_args(tmp_path):
    kinds = tmp_path / "kinds.json"
    kinds.write_text(json.dumps(list(FACT_KINDS)), encoding="utf-8")
    copied = tmp_path / "copied.json"
    copied.write_text(json.dumps(list(COPIED_ATTRIBUTES)), encoding="utf-8")
    return ["--fact-kinds", str(kinds), "--copied-attributes", str(copied)]


def test_selftest_passes_and_names_every_plant(capsys):
    assert validate.main(["--selftest"]) == 0
    out = capsys.readouterr().out
    expected = json.loads(validate.EXPECTED_ERRORS_FILE.read_text(encoding="utf-8"))
    for name, entry in expected.items():
        assert f"plant {name} CAUGHT {entry['check']} ({entry['reason']})" in out
    assert f"selftest.plants PASS {len(expected)} of {len(expected)} plants caught" in out
    assert f"selftest.coverage PASS {len(CHECKS)} of {len(CHECKS)} checks" in out


def test_selftest_fails_when_a_plant_is_declared_for_another_check(tmp_path, monkeypatch, capsys):
    errors = json.loads(validate.EXPECTED_ERRORS_FILE.read_text(encoding="utf-8"))
    errors["fact-no-quote.json"]["check"] = "id.recompute"
    planted = tmp_path / "expected-errors.json"
    planted.write_text(json.dumps(errors), encoding="utf-8")
    monkeypatch.setattr(validate, "EXPECTED_ERRORS_FILE", planted)
    assert validate.main(["--selftest"]) == 1
    assert "plant fact-no-quote.json MISSED id.recompute" in capsys.readouterr().out


def test_selftest_fails_when_a_plant_has_no_declared_reason(tmp_path, monkeypatch, capsys):
    errors = json.loads(validate.EXPECTED_ERRORS_FILE.read_text(encoding="utf-8"))
    del errors["fact-no-quote.json"]
    planted = tmp_path / "expected-errors.json"
    planted.write_text(json.dumps(errors), encoding="utf-8")
    monkeypatch.setattr(validate, "EXPECTED_ERRORS_FILE", planted)
    assert validate.main(["--selftest"]) == 1
    assert "listed in only one of planted/ and expected-errors.json" in capsys.readouterr().out


def test_selftest_fails_when_a_valid_example_is_broken(tmp_path, monkeypatch, capsys):
    examples = tmp_path / "examples"
    shutil.copytree(validate.EXAMPLES_DIR, examples)
    fact = examples / "valid" / "fact.json"
    data = json.loads(fact.read_text(encoding="utf-8"))
    data["quote"] = "changed"
    fact.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(validate, "EXAMPLES_DIR", examples)
    assert validate.main(["--selftest"]) == 1
    assert "id.recompute FAIL fact.json: the id fact:" in capsys.readouterr().out


def test_valid_examples_pass_from_the_command_line(topic_args, capsys):
    assert validate.main([str(validate.EXAMPLES_DIR / "valid"), *topic_args]) == 0
    assert "validate.records PASS 52 records checked" in capsys.readouterr().out


def test_every_planted_example_fails_from_the_command_line(topic_args):
    for path in sorted((validate.EXAMPLES_DIR / "planted").glob("*.json")):
        assert validate.main([str(path), *topic_args]) == 1, path.name


def test_a_rerun_bundle_keeps_the_decision_and_variants_stand_side_by_side(topic_args, capsys):
    valid = validate.EXAMPLES_DIR / "valid"
    for name in ("bundle-rerun.json", "bundle-fact-variants.json"):
        assert validate.main([str(valid / name), *topic_args]) == 0, name
    out = capsys.readouterr().out
    assert "decision.digest-stale PASS 1 bundles examined, 0 failed" in out
    assert "id.duplicate PASS 1 bundles examined, 0 failed" in out


def test_a_wrong_copied_list_breaks_the_fact_ids(tmp_path, topic_args, capsys):
    empty = tmp_path / "none-copied.json"
    empty.write_text("[]", encoding="utf-8")
    args = [*topic_args[:2], "--copied-attributes", str(empty)]
    assert validate.main([str(validate.EXAMPLES_DIR / "valid" / "fact.json"), *args]) == 1
    assert "id.recompute FAIL fact.json" in capsys.readouterr().out


def test_kinds_without_copied_attributes_is_a_failure(topic_args, capsys):
    path = validate.EXAMPLES_DIR / "valid" / "fact.json"
    assert validate.main([str(path), *topic_args[:2]]) == 1
    assert "given together, or neither" in capsys.readouterr().out


def test_zero_records_is_a_failure(tmp_path, capsys):
    assert validate.main([str(tmp_path)]) == 1
    assert "validate.records FAIL 0 records checked" in capsys.readouterr().out


def test_no_paths_is_a_failure(capsys):
    assert validate.main([]) == 1
    assert "no paths given" in capsys.readouterr().out


def test_unreadable_json_is_a_failure(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert validate.main([str(bad)]) == 1
    assert "read FAIL" in capsys.readouterr().out


def test_a_fact_without_the_topic_declaration_fails(capsys):
    assert validate.main([str(validate.EXAMPLES_DIR / "valid" / "fact.json")]) == 1
    assert (
        "fact.kind FAIL fact.json: no topic declaration of fact kinds and copied attributes"
        in capsys.readouterr().out
    )


def test_a_bad_kind_list_is_a_failure(tmp_path, topic_args, capsys):
    kinds = tmp_path / "kinds.json"
    kinds.write_text("[]", encoding="utf-8")
    args = ["--fact-kinds", str(kinds), *topic_args[2:]]
    assert validate.main([str(validate.EXAMPLES_DIR / "valid"), *args]) == 1
    assert "expected a non-empty list of kind names" in capsys.readouterr().out


def test_jsonl_lines_are_independent_records(tmp_path, topic_args, capsys):
    valid = validate.EXAMPLES_DIR / "valid"
    lines = [
        json.loads((valid / name).read_text(encoding="utf-8"))
        for name in ("fact.json", "decision.json")
    ]
    path = tmp_path / "records.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    assert validate.main([str(path), *topic_args]) == 0
    out = capsys.readouterr().out
    assert "validate.records PASS 2 records checked" in out
    assert "ref.resolves" not in out


@pytest.mark.parametrize(
    ("error_type", "check"),
    [
        ("missing", "schema.required"),
        ("literal_error", "schema.enum"),
        ("extra_forbidden", "schema.extra"),
        ("string_pattern_mismatch", "schema.type"),
        ("person.machine", "person.machine"),
    ],
)
def test_check_for_error_maps_pydantic_types(error_type, check):
    assert check_for_error(error_type) == check
