"""Helpers that read the written policy set's Markdown for the tests: control lines and clauses."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field

from context.corpus import POLICIES_DIR
from utils import PROJECT_ROOT

HMB = "harbour-mutual-bank"
SEEDS = PROJECT_ROOT / "evals" / "data" / "policy_seeds.tsv"
SEED_COLUMNS = [
    "seed_id",
    "regulation",
    "provision",
    "provision_quote",
    "binds",
    "documents",
    "clauses",
    "clause_quotes",
    "state",
    "why",
]

_SECTION = re.compile(r"^## (\d+)\. (\S.*)$")
_CLAUSE = re.compile(r"^(\d+)\.(\d+) (\S.*)$", re.DOTALL)
_CONTROL = re.compile(r"^([A-Z][A-Za-z ]+): (\S.*)$")


@dataclass
class PolicyText:
    """A written policy document as the tests read it."""

    title: str
    control: dict[str, str]
    sections: list[tuple[str, str]] = field(default_factory=list)
    clauses: dict[str, str] = field(default_factory=dict)
    words: int = 0


def read_policy(text: str) -> PolicyText:
    """Read a written policy document into its title, control lines, sections and clauses.

    Args:
        text: The document's Markdown.

    Returns:
        The document as the tests read it.

    Raises:
        AssertionError: If a block of a numbered section is not a clause of that section, or
            the document control block holds a line that is not ``Key: value``.
    """
    lines = text.split("\n")
    assert lines[0].startswith("# "), "the first line is the title"
    policy = PolicyText(title=lines[0][2:].strip(), control={}, words=len(text.split()))
    body = "\n".join(lines[1:])
    parts = re.split(r"^(## .*)$", body, flags=re.MULTILINE)
    assert not parts[0].strip(), "nothing stands between the title and the first heading"
    for heading, content in zip(parts[1::2], parts[2::2], strict=True):
        if heading == "## Document control":
            for line in content.strip().split("\n"):
                match = _CONTROL.match(line)
                assert match, f"document control line '{line}' is not 'Key: value'"
                policy.control[match.group(1)] = match.group(2)
            continue
        section = _SECTION.match(heading)
        assert section, f"heading '{heading}' is not a numbered section"
        policy.sections.append((section.group(1), section.group(2)))
        for block in (b.strip() for b in re.split(r"\n\s*\n", content)):
            if not block:
                continue
            clause = _CLAUSE.match(block)
            assert clause, f"block '{block[:60]}' in section {section.group(1)} is not a clause"
            assert clause.group(1) == section.group(1), f"clause {block[:8]} is out of its section"
            number = f"{clause.group(1)}.{clause.group(2)}"
            assert number not in policy.clauses, f"clause {number} appears twice"
            policy.clauses[number] = clause.group(3)
    return policy


def hmb_manifest_documents() -> list[dict[str, str]]:
    """Return the written set's manifest entries, in manifest order."""
    import json

    manifest = json.loads((POLICIES_DIR / HMB / "manifest.json").read_text(encoding="utf-8"))
    return manifest["documents"]


def hmb_policies() -> dict[str, PolicyText]:
    """Return every document of the written set, read, keyed by its manifest id."""
    return {
        entry["id"]: read_policy((POLICIES_DIR / HMB / entry["file"]).read_text(encoding="utf-8"))
        for entry in hmb_manifest_documents()
    }


def read_seeds() -> tuple[list[str], list[dict[str, str]]]:
    """Return the seed register's comment lines and its rows.

    Returns:
        The lines that start with ``#``, without the mark, and each row as a mapping of column
        to value.
    """
    text = SEEDS.read_text(encoding="utf-8")
    comments = [line[1:].strip() for line in text.split("\n") if line.startswith("#")]
    table = [line for line in text.split("\n") if line and not line.startswith("#")]
    rows = list(csv.reader(table, delimiter="\t", quoting=csv.QUOTE_NONE))
    assert rows[0] == SEED_COLUMNS, f"the header is {rows[0]}"
    for row in rows[1:]:
        assert len(row) == len(SEED_COLUMNS), f"row {row[0]} has {len(row)} fields"
    return comments, [dict(zip(SEED_COLUMNS, row, strict=True)) for row in rows[1:]]


def split_evidence(value: str) -> list[str]:
    """Split a seed's list field at ``" | "``; an empty field is an empty list."""
    return [] if not value else value.split(" | ")
