"""Build the reference examples from the starter's labels and the applications."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from evals.labels import LABELS_PATH, LABELS_SHA256, LabelFormatError, read_labels, sha256_of
from utils import db

DATA_DIR = Path(__file__).resolve().parent / "data"
FILE_NAME = "examples.jsonl"
LABELS_MADE_BY = "the starter's authors; carried unchanged, and not made by this repository"
LABELS_SOURCE = (
    "01_kyc_agent/scripts/run_experiments.py, lines 51 to 77, at commit 12acee0 of the starter"
)


@dataclass(frozen=True)
class Built:
    """The file the build produces, and every problem found in the labels."""

    examples: str
    problems: list[str] = field(default_factory=list)
    written: int = 0
    applications: int = 0


def read_examples(*, data_dir: Path = DATA_DIR) -> list[dict]:
    """Read the example file, one JSON object per line.

    Args:
        data_dir: The folder that holds it.

    Returns:
        The examples in file order.
    """
    lines = (data_dir / FILE_NAME).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def build(labels_path: Path = LABELS_PATH) -> Built:
    """Build the examples file and check the labels.

    Args:
        labels_path: The labels file.

    Returns:
        The text of the file and every problem found; the file is not written.

    Raises:
        LabelFormatError: If the labels cannot be read or do not match the applications.
    """
    labels = read_labels(labels_path)
    applications = {row["customer_id"]: row["application"] for row in db.table("applications")}
    problems = []
    digest = sha256_of(labels_path)
    if digest != LABELS_SHA256:
        problems.append(f"the labels' digest {digest} is not the digest on record")
    metadata = {
        "labels_sha256": "sha256:" + digest,
        "labels_made_by": LABELS_MADE_BY,
        "labels_source": LABELS_SOURCE,
    }
    lines = []
    for label in labels:
        example = {
            "key": label.customer_id,
            "inputs": {"customer_id": label.customer_id},
            "reference_outputs": {
                "risk_level": label.risk_level,
                "decision": label.decision,
                "application": applications[label.customer_id],
                "label_reason": label.reason,
                "edge_case": label.edge_case,
            },
            "metadata": {**metadata, "customer_id": label.customer_id},
        }
        lines.append(json.dumps(example, ensure_ascii=False) + "\n")
    return Built(
        examples="".join(lines),
        problems=problems,
        written=len(lines),
        applications=len(applications),
    )


def disk_problems(built: Built, data_dir: Path) -> list[str]:
    """Compare the file in a folder with what the build produces.

    Args:
        built: The result of ``build``.
        data_dir: The folder that should hold the file.

    Returns:
        One sentence if the file is missing or differs; none otherwise.
    """
    path = data_dir / FILE_NAME
    if not path.exists():
        return [f"{FILE_NAME} is missing"]
    if path.read_text(encoding="utf-8") != built.examples:
        return [f"{FILE_NAME} on disk differs from what the build produces"]
    return []


def main(argv: list[str] | None = None) -> int:
    """Build the examples file, or with --check compare it with the file on disk.

    Args:
        argv: Command-line arguments; None reads them from the process.

    Returns:
        0 when the labels are sound and (in check mode) the file on disk matches, otherwise 1.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare with the file on disk")
    parser.add_argument("--labels", type=Path, default=LABELS_PATH)
    parser.add_argument("--out-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)
    try:
        built = build(args.labels)
    except LabelFormatError as error:
        print(f"FAIL {error}")
        return 1
    problems = list(built.problems)
    if args.check:
        problems.extend(disk_problems(built, args.out_dir))
    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        return 1
    if not args.check:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / FILE_NAME).write_text(built.examples, encoding="utf-8", newline="\n")
    verb = "checked" if args.check else "built"
    print(f"{verb} {built.written} of {built.applications} applications")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
