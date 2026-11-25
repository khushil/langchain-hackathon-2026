"""The starter's 25 labels of the applications, read from the data file that carries them."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from utils import db

LABELS_PATH = Path(__file__).resolve().parent / "data" / "starter_labels.tsv"
LABELS_SHA256 = "031f4fb7a4f50ff7147dbcf34d62c990fef9826e929159ff7527b5bf5a1e5750"
"""The digest of the labels file as carried; a label changed by a word changes it."""

HEADER = ("customer_id", "risk_level", "reason")
LEVELS = ("low", "high")
EDGE_PREFIX = "Edge case"


class LabelFormatError(Exception):
    """The labels file cannot be read, or does not match the applications."""


@dataclass(frozen=True)
class Label:
    """The starter's label of one application."""

    customer_id: str
    risk_level: str
    reason: str

    @property
    def decision(self) -> str:
        """The expected decision, derived as the starter derives it."""
        return "reject" if self.risk_level == "high" else "approve"

    @property
    def edge_case(self) -> bool:
        """Whether the starter's reason marks the customer as an edge case."""
        return self.reason.startswith(EDGE_PREFIX)


def sha256_of(path: Path) -> str:
    """Return the SHA-256 of a file's bytes.

    Args:
        path: The file.

    Returns:
        The digest in lower-case hex.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_labels(path: Path = LABELS_PATH) -> list[Label]:
    """Read the labels and check them against the applications.

    Args:
        path: The labels file; lines that begin with ``#`` are comments.

    Returns:
        One label for each application, in the applications' order.

    Raises:
        LabelFormatError: If the header is not the expected one, a row is short, a level is
            neither low nor high, a customer is labelled twice, or the labels and the applications
            do not name the same customers; each is named.
    """
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not lines or tuple(lines[0].split("\t")) != HEADER:
        raise LabelFormatError(f"the labels' header is not {'<TAB>'.join(HEADER)}")
    labels: list[Label] = []
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) != len(HEADER) or not all(c.strip() for c in cells):
            raise LabelFormatError(f"the row '{line[:60]}' is short: it needs {len(HEADER)} cells")
        label = Label(*cells)
        if label.risk_level not in LEVELS:
            raise LabelFormatError(
                f"{label.customer_id} has the risk level '{label.risk_level}', not low or high"
            )
        labels.append(label)
    seen = [x.customer_id for x in labels]
    repeated = sorted({c for c in seen if seen.count(c) > 1})
    if repeated:
        raise LabelFormatError(f"labelled twice: {', '.join(repeated)}")
    applications = [r["customer_id"] for r in db.table("applications")]
    missing, extra = sorted(set(applications) - set(seen)), sorted(set(seen) - set(applications))
    if missing or extra:
        raise LabelFormatError(
            f"the labels and the applications differ: no label for {', '.join(missing) or 'none'}; "
            f"a label for no application: {', '.join(extra) or 'none'}"
        )
    by_id = {x.customer_id: x for x in labels}
    return [by_id[c] for c in applications]
