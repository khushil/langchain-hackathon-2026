"""Export one JSON Schema per record type, or check that the exported files match the record types.

Run ``python -m fsi_common.export_schemas`` to write the files and ``--check`` to compare them,
byte for byte, with what the record types export now.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fsi_common.records import RECORD_TYPES, Record

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def schema_file_name(schema_name: str) -> str:
    """Return the file name of a record type's schema.

    Args:
        schema_name: The record's schema name, for example ``fact.v1``.

    Returns:
        The file name, for example ``fact.v1.schema.json``.
    """
    return f"{schema_name}.schema.json"


def build_schema(record_type: type[Record]) -> dict[str, Any]:
    """Return the JSON Schema of one record type.

    Args:
        record_type: A top-level record type.

    Returns:
        The schema, with the ``schema`` field required and fixed to the type's schema name.
    """
    schema = record_type.model_json_schema(by_alias=True, mode="validation")
    schema["properties"]["schema"] = {"const": record_type.SCHEMA, "type": "string"}
    schema["required"] = sorted({*schema.get("required", []), "schema"})
    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": schema_file_name(record_type.SCHEMA),
        **schema,
    }


def render(schema: dict[str, Any]) -> str:
    """Render a schema in its one byte form.

    Args:
        schema: A JSON Schema.

    Returns:
        Indented JSON with sorted keys and a final newline.
    """
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def expected_files() -> dict[str, str]:
    """Return every schema file name with the text it must hold.

    Returns:
        A mapping from file name to file text, one per record type.
    """
    return {
        schema_file_name(name): render(build_schema(cls))
        for name, cls in sorted(RECORD_TYPES.items())
    }


def main(argv: list[str] | None = None) -> int:
    """Write the schema files, or with ``--check`` report any that differ.

    Args:
        argv: Command-line arguments; ``sys.argv`` when None.

    Returns:
        The exit code: 0 when written or all match, 1 when a file differs, is missing or is extra.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    args = parser.parse_args(argv)
    expected = expected_files()
    if not args.check:
        SCHEMA_DIR.mkdir(exist_ok=True)
        for name, text in expected.items():
            (SCHEMA_DIR / name).write_text(text, encoding="utf-8")
        print(f"schemas.export PASS {len(expected)} schema files written")
        return 0
    present = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
    problems = sorted(f"{name} is missing" for name in set(expected) - present)
    problems += sorted(
        f"{name} is not exported by any record type" for name in present - set(expected)
    )
    for name, text in sorted(expected.items()):
        if name in present and (SCHEMA_DIR / name).read_text(encoding="utf-8") != text:
            problems.append(f"{name} differs from what the record type exports")
    for problem in problems:
        print(f"schemas.match FAIL {problem}")
    status = "FAIL" if problems else "PASS"
    print(
        f"schemas.match {status} {len(expected) - len(problems)} of {len(expected)} "
        "schema files match"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
