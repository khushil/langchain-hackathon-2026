"""Validate record files, or with ``--selftest`` prove the checks catch every planted example.

A ``.json`` file holding one object is one record; a ``.json`` file holding an array is a bundle,
whose records are also checked against each other; a ``.jsonl`` file holds one record per line.
The validator prints one line per check with PASS or FAIL and the count it examined, and exits
non-zero on any failure, on any file it cannot read, and when it checked nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from fsi_common.bundle_checks import check_bundle
from fsi_common.checks import BUNDLE, CHECKS, Finding, validate_record
from fsi_common.export_schemas import SCHEMA_DIR, schema_file_name

EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"
FACT_KINDS_FILE = EXAMPLES_DIR / "fact-kinds.json"
EXPECTED_ERRORS_FILE = EXAMPLES_DIR / "expected-errors.json"


class UnreadableRecordsError(Exception):
    """A record file could not be read or parsed as JSON."""


@dataclass
class Report:
    """What a validation run examined and what it found."""

    examined: Counter[str] = field(default_factory=Counter)
    findings: list[Finding] = field(default_factory=list)
    records: int = 0
    valid_records: list[dict[str, Any]] = field(default_factory=list)


def read_records(path: Path) -> tuple[list[Any], bool]:
    """Read the records of one file.

    Args:
        path: A ``.json`` or ``.jsonl`` file.

    Returns:
        The JSON values read, and whether the file is a bundle.

    Raises:
        UnreadableRecordsError: If the file cannot be read or holds invalid JSON.
    """
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonl":
            return [json.loads(line) for line in text.splitlines() if line.strip()], False
        value = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UnreadableRecordsError(f"{path}: {exc}") from exc
    if isinstance(value, list):
        return value, True
    return [value], False


def validate_file(path: Path, report: Report, *, fact_kinds: frozenset[str] | None) -> None:
    """Validate every record of one file into the report.

    Args:
        path: The file.
        report: The report to add counts and findings to.
        fact_kinds: The topic's closed list of fact kinds.

    Raises:
        UnreadableRecordsError: If the file cannot be read.
    """
    values, is_bundle = read_records(path)
    records = []
    for index, value in enumerate(values):
        where = f"{path.name}[{index}]" if len(values) > 1 else path.name
        schema = value.get("schema") if isinstance(value, dict) else None
        for check, info in CHECKS.items():
            if schema in info.applies_to or (
                check == "schema.unknown" and BUNDLE not in info.applies_to
            ):
                report.examined[check] += 1
        record, findings = validate_record(value, where=where, fact_kinds=fact_kinds)
        report.records += 1
        report.findings += findings
        if record is not None:
            records.append(record)
            report.valid_records.append(value)
    if is_bundle:
        for check, info in CHECKS.items():
            if BUNDLE in info.applies_to:
                report.examined[check] += 1
        if len(records) == len(values):
            report.findings += check_bundle(records, where=path.name)


def check_lines(report: Report) -> list[str]:
    """Return one line per check that examined anything, with PASS or FAIL and its count.

    Args:
        report: A finished report.

    Returns:
        The lines, in the order of the check table.
    """
    failed = Counter(finding.check for finding in report.findings)
    lines = []
    for check, info in CHECKS.items():
        count = report.examined[check]
        if count == 0 and not failed[check]:
            continue
        unit = "bundles" if BUNDLE in info.applies_to else "records"
        status = "FAIL" if failed[check] else "PASS"
        lines.append(f"{check} {status} {count} {unit} examined, {failed[check]} failed")
    return lines


def load_fact_kinds(path: Path) -> frozenset[str]:
    """Read a topic's closed list of fact kinds.

    Args:
        path: A JSON file holding a list of kind names.

    Returns:
        The kinds.

    Raises:
        UnreadableRecordsError: If the file is unreadable or is not a non-empty list of strings.
    """
    try:
        kinds = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UnreadableRecordsError(f"{path}: {exc}") from exc
    if not isinstance(kinds, list) or not kinds or not all(isinstance(k, str) for k in kinds):
        raise UnreadableRecordsError(f"{path}: expected a non-empty list of kind names")
    return frozenset(kinds)


def _files(paths: list[Path]) -> list[Path]:
    found = []
    for path in paths:
        if path.is_dir():
            found += sorted(p for p in path.rglob("*") if p.suffix in {".json", ".jsonl"})
        else:
            found.append(path)
    return found


def run_paths(paths: list[Path], *, fact_kinds: frozenset[str] | None) -> int:
    """Validate the given files and directories and print the check lines.

    Args:
        paths: Files, or directories searched for ``.json`` and ``.jsonl`` files.
        fact_kinds: The topic's closed list of fact kinds.

    Returns:
        The exit code.
    """
    report = Report()
    try:
        for path in _files(paths):
            validate_file(path, report, fact_kinds=fact_kinds)
    except UnreadableRecordsError as exc:
        print(f"read FAIL {exc}")
        return 1
    for finding in report.findings:
        print(f"{finding.check} FAIL {finding.where}: {finding.message}")
    print("\n".join(check_lines(report)))
    if report.records == 0:
        print("validate.records FAIL 0 records checked")
        return 1
    print(
        f"validate.records {'FAIL' if report.findings else 'PASS'} {report.records} records checked"
    )
    return 1 if report.findings else 0


def _schema_validators() -> dict[str, Draft202012Validator]:
    validators = {}
    for path in SCHEMA_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        validators[path.name] = Draft202012Validator(schema)
    return validators


def selftest() -> int:
    """Validate the valid examples, then prove each plant is caught for its declared check.

    Returns:
        The exit code: 0 only when every valid example passes every check and the JSON Schemas,
        and every plant is caught by the check ``expected-errors.json`` declares for it.
    """
    try:
        kinds = load_fact_kinds(FACT_KINDS_FILE)
        expected = json.loads(EXPECTED_ERRORS_FILE.read_text(encoding="utf-8"))
        valid = Report()
        for path in _files([EXAMPLES_DIR / "valid"]):
            validate_file(path, valid, fact_kinds=kinds)
    except (UnreadableRecordsError, OSError, json.JSONDecodeError) as exc:
        print(f"read FAIL {exc}")
        return 1
    ok = not valid.findings and valid.records > 0
    for finding in valid.findings:
        print(f"{finding.check} FAIL {finding.where}: {finding.message}")
    print("\n".join(check_lines(valid)))
    print(
        f"selftest.valid {'PASS' if ok else 'FAIL'} {valid.records} valid example records checked"
    )
    validators = _schema_validators()
    schema_errors = 0
    for value in valid.valid_records:
        errors = list(validators[schema_file_name(value["schema"])].iter_errors(value))
        schema_errors += len(errors)
        for error in errors:
            print(f"jsonschema.valid FAIL {value.get('id')}: {error.message}")
    ok = ok and schema_errors == 0
    print(
        f"jsonschema.valid {'FAIL' if schema_errors else 'PASS'} {len(valid.valid_records)} records"
    )
    return 0 if _plants(expected, kinds) and ok else 1


def _plants(expected: dict[str, dict[str, str]], kinds: frozenset[str]) -> bool:
    planted = {p.name: p for p in _files([EXAMPLES_DIR / "planted"])}
    caught = 0
    for name in sorted(set(planted) | set(expected)):
        if name not in planted or name not in expected:
            print(f"plant {name} FAIL listed in only one of planted/ and expected-errors.json")
            continue
        report = Report()
        try:
            validate_file(planted[name], report, fact_kinds=kinds)
        except UnreadableRecordsError as exc:
            print(f"plant {name} FAIL unreadable: {exc}")
            continue
        declared = expected[name]
        hits = [f for f in report.findings if f.check == declared["check"]]
        others = sorted({f.check for f in report.findings} - {declared["check"]})
        if hits and others:
            print(
                f"plant {name} FAIL caught for {declared['check']} but also for {', '.join(others)}"
            )
        elif hits:
            caught += 1
            print(
                f"plant {name} CAUGHT {declared['check']} ({declared['reason']}): {hits[0].message}"
            )
        else:
            found = ", ".join(sorted({f.check for f in report.findings})) or "nothing"
            print(f"plant {name} MISSED {declared['check']} ({declared['reason']}); found {found}")
    total = len(set(planted) | set(expected))
    passed = total > 0 and caught == total
    print(
        f"selftest.plants {'PASS' if passed else 'FAIL'} {caught} of {total} plants caught "
        "for their declared check and no other"
    )
    unplanted = sorted(set(CHECKS) - {entry["check"] for entry in expected.values()})
    for check in unplanted:
        print(f"selftest.coverage FAIL {check} has no planted case")
    print(
        f"selftest.coverage {'FAIL' if unplanted else 'PASS'} "
        f"{len(CHECKS) - len(unplanted)} of {len(CHECKS)} checks have a planted case"
    )
    return passed and not unplanted


def main(argv: list[str] | None = None) -> int:
    """Run the validator from the command line.

    Args:
        argv: Command-line arguments; ``sys.argv`` when None.

    Returns:
        The exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path, help="record files or directories")
    parser.add_argument("--fact-kinds", type=Path, help="JSON list of the topic's fact kinds")
    parser.add_argument("--selftest", action="store_true", help="run the planted examples")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.paths:
        print("validate.records FAIL no paths given")
        return 1
    try:
        kinds = load_fact_kinds(args.fact_kinds) if args.fact_kinds else None
    except UnreadableRecordsError as exc:
        print(f"read FAIL {exc}")
        return 1
    return run_paths(args.paths, fact_kinds=kinds)


if __name__ == "__main__":
    sys.exit(main())
