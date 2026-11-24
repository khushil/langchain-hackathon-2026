"""Tests that the exported JSON Schemas and the example files match the code that makes them."""

import hashlib
import json

import pytest
from jsonschema import Draft202012Validator

from fsi_common import export_schemas
from fsi_common.examples import build
from fsi_common.records import RECORD_TYPES


def _digests(folder):
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob("*.json"))
    }


def test_schema_files_match_the_record_types(capsys):
    assert export_schemas.main(["--check"]) == 0
    assert (
        f"{len(RECORD_TYPES)} of {len(RECORD_TYPES)} schema files match" in capsys.readouterr().out
    )


def test_re_export_gives_identical_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(export_schemas, "SCHEMA_DIR", tmp_path)
    assert export_schemas.main([]) == 0
    first = _digests(tmp_path)
    assert export_schemas.main([]) == 0
    assert _digests(tmp_path) == first
    assert first == _digests(export_schemas.Path(export_schemas.__file__).parent / "schemas")


def test_schema_check_fails_on_a_changed_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(export_schemas, "SCHEMA_DIR", tmp_path)
    export_schemas.main([])
    (tmp_path / "fact.v1.schema.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "stray.v1.schema.json").write_text("{}\n", encoding="utf-8")
    assert export_schemas.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "fact.v1.schema.json differs" in out
    assert "stray.v1.schema.json is not exported" in out


def test_one_schema_per_record_type():
    names = {p.name for p in (export_schemas.SCHEMA_DIR).glob("*.schema.json")}
    assert names == {f"{name}.schema.json" for name in RECORD_TYPES}


@pytest.fixture(scope="module")
def decision_schema():
    path = export_schemas.SCHEMA_DIR / "decision.v1.schema.json"
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def _decision_with(field: str, value: str) -> dict:
    data = json.loads((build.EXAMPLES_DIR / "valid" / "decision.json").read_text(encoding="utf-8"))
    data["reviewer"][field] = value
    return data


@pytest.mark.parametrize(
    "value", ["", "   ", "claude-sonnet-5-5", "SYSTEM", "system", "Bot", " claude ", "GPT", "AI"]
)
@pytest.mark.parametrize("field", ["name", "role"])
def test_json_schema_alone_refuses_empty_and_machine_reviewers(decision_schema, field, value):
    assert list(decision_schema.iter_errors(_decision_with(field, value)))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "Claude Dupont"),
        ("role", "Head of Model Risk"),
        ("role", "Compliance Assistant"),
        ("role", "Transfer Agent"),
        ("role", "AI and Automation Lead"),
    ],
)
def test_json_schema_accepts_people_whose_words_include_a_machine_word(
    decision_schema, field, value
):
    assert list(decision_schema.iter_errors(_decision_with(field, value))) == []


def test_json_schema_requires_the_schema_field(decision_schema):
    data = json.loads((build.EXAMPLES_DIR / "valid" / "decision.json").read_text(encoding="utf-8"))
    del data["schema"]
    assert any(
        "'schema' is a required property" in e.message for e in decision_schema.iter_errors(data)
    )


def test_example_files_match_the_code_that_builds_them(capsys):
    assert build.main(["--check"]) == 0
    assert "examples.match PASS" in capsys.readouterr().out


def test_example_check_fails_on_a_stray_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build, "EXAMPLES_DIR", tmp_path)
    build.main([])
    (tmp_path / "planted" / "stray.json").write_text("{}\n", encoding="utf-8")
    assert build.main(["--check"]) == 1
    assert "planted/stray.json is not built by this code" in capsys.readouterr().out
