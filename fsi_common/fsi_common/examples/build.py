"""Write the example files, or with ``--check`` confirm the files are what this code builds."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fsi_common.examples.data import FACT_KINDS, build_examples
from fsi_common.examples.plants import planted_files, valid_files

EXAMPLES_DIR = Path(__file__).resolve().parent


def render(value: Any) -> str:
    """Render an example file's JSON in its one byte form.

    Args:
        value: The JSON value.

    Returns:
        Indented JSON with a final newline.
    """
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def expected_files() -> dict[str, str]:
    """Return every example file, by path relative to the examples folder, with its text.

    Returns:
        The valid files, the planted files, ``expected-errors.json`` and ``fact-kinds.json``.
    """
    ex = build_examples()
    files = {f"valid/{name}": render(value) for name, value in valid_files(ex).items()}
    planted = planted_files(ex)
    files |= {f"planted/{name}": render(value) for name, (value, _, _) in planted.items()}
    errors = {
        name: {"check": check, "reason": reason}
        for name, (_, check, reason) in sorted(planted.items())
    }
    files["expected-errors.json"] = render(errors)
    files["fact-kinds.json"] = render(list(FACT_KINDS))
    return files


def main(argv: list[str] | None = None) -> int:
    """Write the example files, or with ``--check`` report any that differ.

    Args:
        argv: Command-line arguments; ``sys.argv`` when None.

    Returns:
        The exit code: 0 when written or all match, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    args = parser.parse_args(argv)
    expected = expected_files()
    if not args.check:
        for name, text in expected.items():
            path = EXAMPLES_DIR / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(text, encoding="utf-8")
        print(f"examples.build PASS {len(expected)} example files written")
        return 0
    present = {str(p.relative_to(EXAMPLES_DIR)) for p in EXAMPLES_DIR.rglob("*.json")}
    problems = [f"{name} is missing" for name in sorted(set(expected) - present)]
    problems += [f"{name} is not built by this code" for name in sorted(present - set(expected))]
    problems += [
        f"{name} differs from what this code builds"
        for name in sorted(set(expected) & present)
        if (EXAMPLES_DIR / name).read_text(encoding="utf-8") != expected[name]
    ]
    for problem in problems:
        print(f"examples.match FAIL {problem}")
    status = "FAIL" if problems else "PASS"
    print(
        f"examples.match {status} {len(expected) - len(problems)} of {len(expected)} "
        "example files match"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
