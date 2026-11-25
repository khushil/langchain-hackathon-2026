"""Build the evaluation examples from the starter's own reference data, and check them.

The starter ships three reference files for this topic: the analysts' labels for the eleven
transactions before 19 October, the two replies its scripted reviewer gives when asked, and the
four reviews its third module simulates for the week after. Each becomes part of one example: a
customer's stream as inputs, the labels as the reference. Nothing is made up and nothing is
changed; ``python -m evals.build_dataset --check`` fails when the file on disk differs from what
the starter's files give, or when a file breaks the starter's own rule.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.state import OCT_19

DATA_DIR = Path(__file__).resolve().parent / "data"
SOURCE_DIR = Path(__file__).resolve().parents[1] / "data"
EXAMPLES_FILE = "examples.jsonl"
BLOCK_FROM = 70
GREY_FROM = 30


@dataclass(frozen=True)
class Built:
    """The examples, the text of their file, what is wrong with the sources, and the counts."""

    examples: list[dict[str, Any]]
    text: str
    problems: list[str]
    counts: dict[str, str]


def _table(source: Path, name: str) -> list[dict[str, Any]]:
    lines = (source / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def label_from_score(score: int) -> dict[str, Any]:
    """Turn a reviewer's score into a label by the starter's rule (block from 70, grey 30 to 69).

    Args:
        score: The score a reviewer would give.

    Returns:
        The decision, the score and whether it is ambiguous.
    """
    return {
        "decision": "block" if score >= BLOCK_FROM else "approve",
        "risk_score": score,
        "ambiguous": GREY_FROM <= score < BLOCK_FROM,
    }


def _label_problems(labels: list[dict[str, Any]], known: set[str]) -> list[str]:
    problems = []
    for label in labels:
        tx, score = label["transaction_id"], label["risk_score"]
        if tx not in known:
            problems.append(f"{tx} has an analyst label and there is no such transaction")
            continue
        wanted = label_from_score(score)
        if label["decision"] != wanted["decision"] or label["ambiguous"] != wanted["ambiguous"]:
            problems.append(
                f"{tx}: the label says {label['decision']} at {score} with ambiguous "
                f"{label['ambiguous']}, and the starter's rule is block from {BLOCK_FROM}, "
                f"ambiguous from {GREY_FROM} to {BLOCK_FROM - 1}"
            )
    return problems


def build(source: Path = SOURCE_DIR) -> Built:
    """Build the examples from the starter's files.

    Args:
        source: The folder holding the starter's JSONL tables.

    Returns:
        The examples, the text of the file that holds them, every problem found in the starter's
        files, and the counts of what was used.
    """
    customers = _table(source, "customer_profiles")
    transactions = _table(source, "transactions")
    labels = _table(source, "analyst_labels")
    replies = {r["transaction_id"]: r for r in _table(source, "reviewer_answers")}
    reviews = {r["transaction_id"]: r for r in _table(source, "simulated_annotations")}
    known = {t["transaction_id"] for t in transactions}
    by_tx = {label["transaction_id"]: label for label in labels}
    problems = _label_problems(labels, known)
    problems += [
        f"{tx} has a simulated review and there is no such transaction"
        for tx in reviews
        if tx not in known
    ]
    for tx in replies:
        if tx not in by_tx or not by_tx[tx]["ambiguous"]:
            problems.append(f"{tx} has a scripted reply and is not ambiguous in the labels")
    examples, used = [], {"labels": 0, "reviews": 0, "replies": 0, "transactions": 0}

    def stream(user_id: str) -> list[dict[str, Any]]:
        rows = [t for t in transactions if t["user_id"] == user_id]
        return sorted(rows, key=lambda t: (t["timestamp"], t["transaction_id"]))

    for customer in customers:
        user_id = customer["user_id"]
        before = [t for t in stream(user_id) if t["timestamp"] < OCT_19]
        if not before:
            continue
        ids = [t["transaction_id"] for t in before]
        problems += [f"{tx} has no label and no simulated review" for tx in ids if tx not in by_tx]
        examples.append(
            {
                "key": f"{user_id}/before-19-october",
                "inputs": {
                    "user_id": user_id,
                    "end": OCT_19,
                    "transactions": before,
                    "reviewer_answers": {tx: replies[tx] for tx in ids if tx in replies},
                },
                "reference_outputs": {"labels": {tx: by_tx[tx] for tx in ids if tx in by_tx}},
                "metadata": {"customer": user_id},
            }
        )
        used["labels"] += sum(tx in by_tx for tx in ids)
        used["replies"] += sum(tx in replies for tx in ids)
    for customer in customers:
        user_id = customer["user_id"]
        after = [t for t in stream(user_id) if t["timestamp"] >= OCT_19]
        if not after:
            continue
        ids = [t["transaction_id"] for t in after]
        problems += [
            f"{tx} has no label and no simulated review" for tx in ids if tx not in reviews
        ]
        labels_after = {
            tx: {
                **label_from_score(reviews[tx]["correct_risk_score"]),
                "comment": reviews[tx]["comment"],
            }
            for tx in ids
            if tx in reviews
        }
        examples.append(
            {
                "key": f"{user_id}/from-19-october",
                "inputs": {
                    "user_id": user_id,
                    "start": OCT_19,
                    "transactions": after,
                    "reviewer_answers": {},
                },
                "reference_outputs": {"labels": labels_after},
                "metadata": {"customer": user_id},
            }
        )
        used["reviews"] += len(labels_after)
    used["transactions"] = sum(len(e["inputs"]["transactions"]) for e in examples)
    counts = {
        "labels": f"{used['labels']} of {len(labels)} analyst labels used",
        "reviews": f"{used['reviews']} of {len(reviews)} simulated reviews used",
        "replies": f"{used['replies']} of {len(replies)} scripted reviewer replies used",
        "transactions": f"{used['transactions']} of {len(transactions)} transactions in an example",
    }
    text = "".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in examples)
    return Built(examples, text, problems, counts)


def read_examples(data_dir: Path = DATA_DIR) -> list[dict[str, Any]]:
    """Read the examples from their file.

    Args:
        data_dir: The folder that holds ``examples.jsonl``.

    Returns:
        The examples, in file order.
    """
    lines = (data_dir / EXAMPLES_FILE).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def disk_problems(built: Built, data_dir: Path = DATA_DIR) -> list[str]:
    """Say whether the file on disk is what the build gives.

    Args:
        built: The build.
        data_dir: The folder that should hold ``examples.jsonl``.

    Returns:
        A problem naming the file when it is missing or differs; empty when it is the build's.
    """
    path = data_dir / EXAMPLES_FILE
    if not path.is_file() or path.read_text(encoding="utf-8") != built.text:
        return [
            f"{path} differs from what the starter's files give, or is missing; "
            "run python -m evals.build_dataset to write it"
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    """Build the examples; write the file, or with ``--check`` only compare it.

    Args:
        argv: Command-line arguments; None reads them from the process.

    Returns:
        0 when the build has no problem and the file is, or is made, what the build gives.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when the file differs")
    parser.add_argument("--out-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)
    built = build()
    for problem in built.problems:
        print(f"FAIL {problem}")
    if built.problems:
        return 1
    if args.check:
        found = disk_problems(built, args.out_dir)
        for problem in found:
            print(f"FAIL {problem}")
        if found:
            return 1
    else:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / EXAMPLES_FILE).write_text(built.text, encoding="utf-8")
    for count in built.counts.values():
        print(count)
    print(f"{len(built.examples)} examples in {args.out_dir / EXAMPLES_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
