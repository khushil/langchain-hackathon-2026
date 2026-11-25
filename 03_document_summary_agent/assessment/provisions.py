"""Provision labels as people write them, placed on the reader's anchors; seeds matched to them.

A seed names its provision as a reader cites it ("Article 30(2), point (b)", "Principle 5.1").
``resolve_provision`` turns that into a place: a unit anchor or a structure node, and the finer
point labels below it. ``match_seed`` finds the obligations of the register at that place, and
the measures compare the seed's state with the state found there, derived by ``derive_state``
when the place holds more than one obligation or point.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from assessment.records import STATES, Obligation, Register, State
from context.errors import ContextError
from utils import PROJECT_ROOT

SEEDS_FILE = PROJECT_ROOT / "evals" / "data" / "policy_seeds.tsv"

REGULATION_KEYS = {"DORA": "DORA", "AI Act": "AI-ACT", "SS1/23": "SS1-23"}
"""The seed file's regulation names, with the manifest's keys."""

_POINTS = (
    r"((?:\s*,?\s*(?:first|second|third|fourth) subparagraph)?"
    r"(?:,?\s*points?)?\s*(?:\([a-z0-9]+\))*)"
)
_ARTICLE = re.compile(r"^Article (\d+)(?:\((\d+)\))?" + _POINTS + r"$")
_ANNEX = re.compile(r"^Annex ([IVX]+)(?:, point (\d+))?" + _POINTS + r"$")
_PRINCIPLE = re.compile(r"^Principle (\d)\.(\d)((?:\([a-z]+\))*)$")
_PARAGRAPH = re.compile(r"^[Pp]aragraph (\d+\.\d+)$")
_LABELS = re.compile(r"\(([a-z0-9]+)\)")


class ProvisionLabelError(ContextError):
    """A provision label cannot be placed on a unit or a heading of its regulation."""


@dataclass(frozen=True)
class ProvisionRef:
    """A place in a regulation: a unit anchor or a structure node, and finer point labels."""

    regulation: str
    anchor: str
    points: tuple[str, ...]


@dataclass(frozen=True)
class Seed:
    """One row of ``policy_seeds.tsv``, with documents and clauses paired in step."""

    seed_id: str
    regulation: str
    provision: str
    state: State
    clauses: tuple[tuple[str, str], ...]
    provision_quote: str = ""
    clause_quotes: tuple[str, ...] = ()


def resolve_provision(regulation: str, label: str) -> ProvisionRef:
    """Place a provision label on the regulation reader's anchors.

    Args:
        regulation: The seed file's name for the regulation (``DORA``, ``AI Act``, ``SS1/23``)
            or a manifest key.
        label: The label, for example ``Article 30(3), point (e)(i)``.

    Returns:
        The place. A sub-principle with no unit of its own (``Principle 5.1``) is its structure
        node, ``subprinciple:5.1``.

    Raises:
        ProvisionLabelError: If the label has none of the forms the regulations use.
    """
    key = REGULATION_KEYS.get(regulation, regulation)
    text = label.strip()
    if key in ("DORA", "AI-ACT"):
        if found := _ARTICLE.match(text):
            article, paragraph, rest = found.groups()
            anchor = f"art:{article}/{paragraph}" if paragraph else f"art:{article}"
            return ProvisionRef(key, anchor, tuple(_LABELS.findall(rest)))
        if found := _ANNEX.match(text):
            annex, point, rest = found.groups()
            anchor = f"anx:{annex}/{point}" if point else f"anx:{annex}"
            return ProvisionRef(key, anchor, tuple(_LABELS.findall(rest)))
    if key == "SS1-23":
        if found := _PRINCIPLE.match(text):
            principle, sub, rest = found.groups()
            labels = _LABELS.findall(rest)
            if len(labels) > 2:
                raise ProvisionLabelError(f"The label {label!r} of {regulation} cannot be placed.")
            if not labels:
                return ProvisionRef(key, f"subprinciple:{principle}.{sub}", ())
            return ProvisionRef(key, f"prin:{principle}.{sub}/{labels[0]}", tuple(labels[1:]))
        if found := _PARAGRAPH.match(text):
            return ProvisionRef(key, f"para:{found.group(1)}", ())
    raise ProvisionLabelError(f"The label {label!r} of {regulation} cannot be placed.")


def load_seeds(path: Path = SEEDS_FILE) -> list[Seed]:
    """Read every seed row, skipping the commented header and change log.

    Args:
        path: The seed file.

    Returns:
        The seeds in file order.

    Raises:
        ProvisionLabelError: If a row's documents and clauses are not in step, or its state is
            not one of the four.
    """
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line[:1] != "#"]
    seeds = []
    for row in csv.DictReader(lines, delimiter="\t"):
        documents = [d.strip() for d in row["documents"].split("|") if d.strip()]
        clauses = [c.strip() for c in row["clauses"].split("|") if c.strip()]
        quotes = [q.strip() for q in row["clause_quotes"].split(" | ") if q.strip()]
        if (
            len(documents) != len(clauses)
            or len(quotes) != len(clauses)
            or row["state"] not in STATES
        ):
            raise ProvisionLabelError(f"The seed {row['seed_id']} in {path} is not in step.")
        seeds.append(
            Seed(
                seed_id=row["seed_id"],
                regulation=REGULATION_KEYS[row["regulation"]],
                provision=row["provision"],
                state=row["state"],  # type: ignore[arg-type]
                clauses=tuple(zip(documents, clauses, strict=True)),
                provision_quote=row["provision_quote"],
                clause_quotes=tuple(quotes),
            )
        )
    return seeds


def match_seed(seed: Seed, register: Register) -> list[Obligation]:
    """Find the obligations a seed is measured against.

    A unit anchor gives its one obligation; a structure node gives every obligation whose unit
    sits under it, which the reader records in each unit's parents.

    Args:
        seed: The seed.
        register: The register.

    Returns:
        The obligations at the seed's place, in register order; empty when none.
    """
    ref = resolve_provision(seed.regulation, seed.provision)
    same = [o for o in register.obligations if o.regulation == ref.regulation]
    exact = [o for o in same if o.anchor == ref.anchor]
    if exact:
        return exact
    return [o for o in same if ref.anchor in o.parents]


def derive_state(states: Iterable[State]) -> State:
    """Derive one state from the states of a group of points or obligations.

    In conflict if any is; covered if all are; not covered if all are; otherwise partly covered.

    Args:
        states: The states of the group.

    Returns:
        The group's state.

    Raises:
        ValueError: If the group holds no state.
    """
    group = list(states)
    if not group:
        raise ValueError("A group with no state has no derived state.")
    if "in conflict" in group:
        return "in conflict"
    if all(s == "covered" for s in group):
        return "covered"
    if all(s == "not covered" for s in group):
        return "not covered"
    return "partly covered"
