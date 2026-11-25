"""The policy seeds as the measures' dataset: read from the seeds file and counted by regulation."""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SEEDS_FILE = Path(__file__).resolve().parent / "data" / "policy_seeds.tsv"
"""The seeded cases of the policy set, one row each, written before any engine run."""

STATES = ("covered", "partly covered", "not covered", "in conflict")
GAP_STATES = ("partly covered", "not covered", "in conflict")
"""A seeded gap is any state other than covered."""

REGULATION_LABELS = {"DORA": "DORA", "AI-ACT": "AI Act", "SS1-23": "SS1/23"}
"""The manifest's regulation keys, with the names the printed lines use."""

_FILE_NAMES = {"DORA": "DORA", "AI Act": "AI-ACT", "SS1/23": "SS1-23"}
"""The seeds file's regulation names, with the manifest's keys."""

_COLUMNS = (
    "seed_id",
    "regulation",
    "provision",
    "provision_quote",
    "documents",
    "clauses",
    "clause_quotes",
    "state",
)


class SeedFileError(Exception):
    """The seeds file is missing, lacks a column or holds a row that cannot be read."""


@dataclass(frozen=True)
class SeedCase:
    """One seeded case: a provision, the state the labels give it and the clauses bearing on it."""

    seed_id: str
    regulation: str
    provision: str
    provision_quote: str
    state: str
    clauses: tuple[tuple[str, str], ...]
    clause_quotes: tuple[str, ...]


@dataclass(frozen=True)
class Populations:
    """The seeds of one regulation, counted the ways the measures need.

    ``regulation`` is a manifest key, or ``all`` for the three together.
    """

    regulation: str
    seeds: int
    gaps: int
    covered: int
    with_clauses: int


def _split(cell: str, separator: str) -> list[str]:
    return [part.strip() for part in cell.split(separator) if part.strip()]


def read_seeds(path: Path = SEEDS_FILE) -> list[SeedCase]:
    """Read every seed row of the seeds file, skipping its commented header and change log.

    Args:
        path: The seeds file.

    Returns:
        The seeds in file order.

    Raises:
        SeedFileError: If the file cannot be read, lacks a column, or a row has no id, a
            regulation or state this repository does not know, an id used twice, or documents,
            clauses and quotes that are not lists of one length.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SeedFileError(f"The seeds file {path} cannot be read: {exc}") from exc
    lines = [line for line in text.splitlines() if line[:1] != "#"]
    reader = csv.DictReader(lines, delimiter="\t")
    missing = [name for name in _COLUMNS if name not in (reader.fieldnames or [])]
    if missing:
        raise SeedFileError(f"The seeds file {path} has no column {', '.join(missing)}.")
    seeds: list[SeedCase] = []
    seen: set[str] = set()
    for row in reader:
        seed_id = (row["seed_id"] or "").strip()
        if not seed_id:
            raise SeedFileError(f"A row of {path} has no seed id.")
        if seed_id in seen:
            raise SeedFileError(f"The seed {seed_id} is in {path} twice.")
        seen.add(seed_id)
        if row["regulation"] not in _FILE_NAMES:
            raise SeedFileError(f"The seed {seed_id} names the regulation {row['regulation']!r}.")
        if row["state"] not in STATES:
            raise SeedFileError(f"The seed {seed_id} has the state {row['state']!r}.")
        documents = _split(row["documents"], "|")
        clauses = _split(row["clauses"], "|")
        quotes = _split(row["clause_quotes"], " | ")
        if not len(documents) == len(clauses) == len(quotes):
            raise SeedFileError(
                f"The seed {seed_id} in {path} is not in step: {len(documents)} documents, "
                f"{len(clauses)} clauses and {len(quotes)} quotes."
            )
        seeds.append(
            SeedCase(
                seed_id=seed_id,
                regulation=_FILE_NAMES[row["regulation"]],
                provision=row["provision"].strip(),
                provision_quote=row["provision_quote"].strip(),
                state=row["state"],
                clauses=tuple(zip(documents, clauses, strict=True)),
                clause_quotes=tuple(quotes),
            )
        )
    return seeds


def populations(seeds: Sequence[SeedCase]) -> list[Populations]:
    """Count the seeds of each regulation, then of all three.

    Args:
        seeds: The seeds.

    Returns:
        One entry per regulation in the order DORA, AI Act, SS1/23, then ``all``.
    """
    entries = []
    for key in (*REGULATION_LABELS, "all"):
        chosen = [s for s in seeds if key in ("all", s.regulation)]
        entries.append(
            Populations(
                regulation=key,
                seeds=len(chosen),
                gaps=sum(1 for s in chosen if s.state in GAP_STATES),
                covered=sum(1 for s in chosen if s.state == "covered"),
                with_clauses=sum(1 for s in chosen if s.clauses),
            )
        )
    return entries


def examples(seeds: Sequence[SeedCase]) -> list[dict[str, Any]]:
    """Make one dataset example per seed: the provision as input, the labels as output.

    Args:
        seeds: The seeds.

    Returns:
        Examples in seed order, each with ``inputs``, ``outputs`` and ``metadata``.
    """
    return [
        {
            "inputs": {
                "seed_id": s.seed_id,
                "regulation": REGULATION_LABELS[s.regulation],
                "provision": s.provision,
                "provision_quote": s.provision_quote,
            },
            "outputs": {
                "state": s.state,
                "clauses": [{"document": d, "clause": c} for d, c in s.clauses],
                "clause_quotes": list(s.clause_quotes),
            },
            "metadata": {"regulation": s.regulation, "gap": s.state in GAP_STATES},
        }
        for s in seeds
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Read the seeds file and print its populations; exit 2 when it cannot be read.

    Args:
        argv: The command line without the program name.

    Returns:
        0 when the file reads, 2 when it does not.
    """
    parser = argparse.ArgumentParser(description="Check the policy seeds file and count it.")
    parser.add_argument("--check", action="store_true", help="read the file and print its counts")
    parser.add_argument("--seeds", type=Path, default=SEEDS_FILE, help="the seeds file")
    args = parser.parse_args(argv)
    try:
        seeds = read_seeds(args.seeds)
    except SeedFileError as exc:
        print(exc, file=sys.stderr)
        return 2
    counts = populations(seeds)
    print(f"{len(seeds)} seeds read from {args.seeds.name}")
    for entry in counts:
        label = REGULATION_LABELS.get(entry.regulation, entry.regulation)
        print(f"{label}: {entry.seeds} seeds, {entry.gaps} gaps, {entry.covered} covered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
