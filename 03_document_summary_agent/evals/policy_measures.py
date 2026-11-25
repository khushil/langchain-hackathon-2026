"""The four measures of the policy assessment, counted by regulation from the bundle's seed matches.

The seeded cases of the Harbour Mutual Bank policy set say what the documents in force state against
55 provisions. A run's ``seed_matches.jsonl`` says what the assessments found at the same places.
Each measure is a count over a stated population, printed as "N of M" for DORA, the AI Act, SS1/23
and all three. The labels come from the seeds file alone, so the engine cannot change what it is
scored against, and nothing here imports the engine or calls a model.

    python -m evals.policy_measures <bundle folder>
    python -m evals.policy_measures --seed-matches <seed_matches.jsonl>
    python -m evals.policy_measures --selftest
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from assessment.provisions import ProvisionLabelError, resolve_provision

from .policy_dataset import (
    GAP_STATES,
    REGULATION_LABELS,
    STATES,
    SeedCase,
    SeedFileError,
    read_seeds,
)

MEASURES = ("seeded_gaps_found", "same_state", "false_gaps", "wrong_citations")
"""The measures, in the order their lines print."""

LOWER_IS_BETTER = frozenset({"false_gaps", "wrong_citations"})
"""The measures whose numerator counts a fault."""

SCOPES = (*REGULATION_LABELS, "all")
"""The regulations a figure is counted for, then all three."""

_PHRASES = {
    "seeded_gaps_found": "seeded gaps",
    "same_state": "seeds",
    "false_gaps": "seeds the labels hold as covered",
    "wrong_citations": "seeds that name clauses and were found as anything but not covered",
}

Clause = tuple[str, str]
"""A clause as a pair: the document's id and the clause's number."""


class MeasureInputError(Exception):
    """A seed matches file cannot be read, or its rows do not agree with the seeds file."""


@dataclass(frozen=True)
class MatchRow:
    """What a run found at one seed's place, as its seed matches file records it."""

    seed_id: str
    regulation: str
    target: str
    points: tuple[str, ...]
    found_state: str
    seeded_state: str
    cited: tuple[Clause, ...]
    seeded: tuple[Clause, ...]


@dataclass(frozen=True)
class Count:
    """One figure: a measure for one regulation, with the seeds it counted and its population."""

    measure: str
    scope: str
    numerator: int
    denominator: int
    counted: tuple[str, ...]
    population: tuple[str, ...]

    def line(self) -> str:
        """Return the figure as the run prints it."""
        label = REGULATION_LABELS.get(self.scope, self.scope)
        head = f"{self.measure} [{label}]: "
        if self.denominator == 0:
            return head + "none in scope"
        return head + f"{self.numerator} of {self.denominator} {_PHRASES[self.measure]}"


@dataclass(frozen=True)
class Report:
    """Every figure of one run, and the seeds that no figure could be taken from."""

    counts: tuple[Count, ...]
    unmatched: tuple[str, ...]
    uncompared: tuple[str, ...]
    total_seeds: int


def _clauses(value: object, where: str, field: str) -> tuple[Clause, ...]:
    if not isinstance(value, list):
        raise MeasureInputError(f"{where}: {field} is not a list.")
    pairs = []
    for item in value:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("document"), str)
            or not isinstance(item.get("clause"), str)
        ):
            raise MeasureInputError(
                f"{where}: {field} holds an entry that has no document and clause."
            )
        pairs.append((item["document"], item["clause"]))
    return tuple(pairs)


def _points(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(p, str) and p.strip() for p in value):
        raise MeasureInputError(f"{where}: points is not a list of point labels.")
    return tuple(value)


def _text(row: dict, where: str, field: str, allowed: Sequence[str] | None = None) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise MeasureInputError(f"{where}: {field} is missing or blank.")
    if allowed is not None and value not in allowed:
        raise MeasureInputError(f"{where}: {field} is {value!r}, not one of {', '.join(allowed)}.")
    return value


def read_seed_matches(path: Path) -> list[MatchRow]:
    """Read a run's ``seed_matches.jsonl``, every line.

    Args:
        path: The file.

    Returns:
        One row per line, in file order; none when the file is empty.

    Raises:
        MeasureInputError: If the file cannot be read, or a line is not JSON, lacks a field or
            holds a state, a regulation or a clause list the measures cannot use.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MeasureInputError(f"The seed matches file {path} cannot be read: {exc}") from exc
    rows: list[MatchRow] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path} line {number}"
        try:
            data = json.loads(line)
        except ValueError as exc:
            raise MeasureInputError(f"{where}: the line is not JSON ({exc}).") from exc
        if not isinstance(data, dict):
            raise MeasureInputError(f"{where}: the line is not an object.")
        rows.append(
            MatchRow(
                seed_id=_text(data, where, "seed_id"),
                regulation=_text(data, where, "regulation", tuple(REGULATION_LABELS)),
                target=_text(data, where, "target"),
                points=_points(data.get("points"), where),
                found_state=_text(data, where, "found_state", STATES),
                seeded_state=_text(data, where, "seeded_state", STATES),
                cited=_clauses(data.get("cited_clauses"), where, "cited_clauses"),
                seeded=_clauses(data.get("seeded_clauses"), where, "seeded_clauses"),
            )
        )
    return rows


def _check_placement(seed: SeedCase, row: MatchRow) -> None:
    """Refuse a match placed on another obligation than the one its seed's provision names."""
    try:
        place = resolve_provision(seed.regulation, seed.provision)
    except ProvisionLabelError as exc:
        raise MeasureInputError(
            f"The seed {seed.seed_id} names the provision {seed.provision!r}, "
            f"which cannot be placed: {exc}"
        ) from exc
    if row.target != place.anchor:
        raise MeasureInputError(
            f"The match for {seed.seed_id} is placed on {row.target}, where the seed's "
            f"provision {seed.provision!r} is {place.anchor}."
        )
    if row.points != place.points:
        raise MeasureInputError(
            f"The match for {seed.seed_id} is placed at the point {list(row.points)}, where "
            f"the seed's provision {seed.provision!r} has {list(place.points)}."
        )


def _check_matches(seeds: Sequence[SeedCase], matches: Sequence[MatchRow]) -> dict[str, MatchRow]:
    by_seed = {s.seed_id: s for s in seeds}
    found: dict[str, MatchRow] = {}
    for row in matches:
        seed = by_seed.get(row.seed_id)
        if seed is None:
            raise MeasureInputError(
                f"The matches name the seed {row.seed_id}, which the seeds file does not hold."
            )
        if row.seed_id in found:
            raise MeasureInputError(f"The match for {row.seed_id} appears twice.")
        if row.regulation != seed.regulation:
            raise MeasureInputError(
                f"The match for {row.seed_id} names the regulation {row.regulation}, "
                f"where the seeds file has {seed.regulation}."
            )
        if row.seeded_state != seed.state:
            raise MeasureInputError(
                f"The match for {row.seed_id} holds the seeded state {row.seeded_state!r}, "
                f"where the seeds file has {seed.state!r}."
            )
        if set(row.seeded) != set(seed.clauses):
            raise MeasureInputError(
                f"The match for {row.seed_id} lists seeded clauses that the seeds file does not."
            )
        _check_placement(seed, row)
        found[row.seed_id] = row
    return found


def _flags(seed: SeedCase, match: MatchRow | None) -> dict[str, tuple[bool, bool]]:
    """Return, per measure, whether the seed is in its population and whether it is counted."""
    found = match.found_state if match else None
    gap = seed.state in GAP_STATES
    covered = seed.state == "covered"
    cites = bool(seed.clauses) and found is not None and found != "not covered"
    wrong = cites and match is not None and not set(match.cited) & set(seed.clauses)
    return {
        "seeded_gaps_found": (gap, gap and found is not None and found != "covered"),
        "same_state": (True, found == seed.state),
        "false_gaps": (covered, covered and found is not None and found != "covered"),
        "wrong_citations": (cites, bool(wrong)),
    }


def measure_seeds(seeds: Sequence[SeedCase], matches: Sequence[MatchRow]) -> Report:
    """Count the four measures for each regulation and for all three.

    A seed with no match stays in every population it belongs to and is never counted as found,
    so a run that skipped a seed scores lower on the two higher-is-better measures. It does not
    score worse on the two lower-is-better ones, so it is listed and the command fails under
    ``--require-all``.

    Args:
        seeds: The seeded cases, which give each population and every label.
        matches: What the run found, one row per seed it matched.

    Returns:
        Every figure, the seeds with no match, and the seeds the run cited a clause for where the
        seeds file names none (which no measure compares).

    Raises:
        MeasureInputError: If a match names a seed the file lacks, repeats a seed, or disagrees with
            the file on the seed's regulation, state or clauses, or is placed on another
            obligation than the seed's provision, or a seed's provision cannot be placed.
    """
    found = _check_matches(seeds, matches)
    flags = {s.seed_id: _flags(s, found.get(s.seed_id)) for s in seeds}
    counts = []
    for measure in MEASURES:
        for scope in SCOPES:
            chosen = [s.seed_id for s in seeds if scope in ("all", s.regulation)]
            population = tuple(i for i in chosen if flags[i][measure][0])
            counted = tuple(i for i in population if flags[i][measure][1])
            counts.append(Count(measure, scope, len(counted), len(population), counted, population))
    return Report(
        counts=tuple(counts),
        unmatched=tuple(s.seed_id for s in seeds if s.seed_id not in found),
        uncompared=tuple(
            s.seed_id
            for s in seeds
            if s.seed_id in found and not s.clauses and found[s.seed_id].cited
        ),
        total_seeds=len(seeds),
    )


def count_of(report: Report, measure: str, scope: str) -> Count:
    """Return one figure of a report.

    Args:
        report: The report.
        measure: One of ``MEASURES``.
        scope: A regulation key, or ``all``.

    Returns:
        The figure.

    Raises:
        KeyError: If the report holds no such figure.
    """
    for count in report.counts:
        if count.measure == measure and count.scope == scope:
            return count
    raise KeyError(f"The report holds no figure {measure} for {scope}.")


def report_lines(report: Report) -> list[str]:
    """Return the figures as printed lines, measure by measure, regulation by regulation."""
    return [count.line() for count in report.counts]


# Planted faults. Each starts from matches that score in full and changes one thing.

Matches = list[MatchRow]
Applier = Callable[[Sequence[SeedCase], Matches], Matches]


@dataclass(frozen=True)
class Plant:
    """One fault: how it changes a run's matches and the measures that must fall as a result."""

    name: str
    description: str
    degrades: tuple[str, ...]
    apply: Applier


@dataclass(frozen=True)
class PlantResult:
    """Whether a plant was caught: the measures that fell, against the ones declared."""

    name: str
    degraded: list[str]
    expected: list[str]

    @property
    def caught(self) -> bool:
        """True when the measures that fell are exactly the declared ones."""
        return bool(self.expected) and self.degraded == self.expected

    def line(self) -> str:
        """One line for the report, CAUGHT or MISSED, with the measures that fell."""
        if self.caught:
            return f"CAUGHT {self.name}: {', '.join(self.degraded)} fell"
        fell = ", ".join(self.degraded) or "nothing"
        return f"MISSED {self.name}: expected {', '.join(self.expected)} to fall, but {fell} fell"


def perfect_matches(seeds: Sequence[SeedCase]) -> Matches:
    """Return the matches of a run that agrees with every label.

    Args:
        seeds: The seeds.

    Returns:
        One row per seed: the seeded state found, and the seeded clauses cited unless the seeded
        state is not covered.
    """
    rows = []
    for s in seeds:
        place = resolve_provision(s.regulation, s.provision)
        cited = () if s.state == "not covered" else s.clauses
        rows.append(
            MatchRow(
                s.seed_id,
                s.regulation,
                place.anchor,
                place.points,
                s.state,
                s.state,
                cited,
                s.clauses,
            )
        )
    return rows


def _change(matches: Matches, seed_id: str, **update: object) -> Matches:
    return [dataclasses.replace(m, **update) if m.seed_id == seed_id else m for m in matches]


def _first(seeds: Sequence[SeedCase], test: Callable[[SeedCase], bool]) -> SeedCase:
    return next(s for s in seeds if test(s))


def _gap_found_as_covered(seeds: Sequence[SeedCase], matches: Matches) -> Matches:
    seed = _first(seeds, lambda s: s.state == "partly covered" and bool(s.clauses))
    return _change(matches, seed.seed_id, found_state="covered")


def _state_changed_between_gaps(seeds: Sequence[SeedCase], matches: Matches) -> Matches:
    seed = _first(seeds, lambda s: s.state == "partly covered" and bool(s.clauses))
    return _change(matches, seed.seed_id, found_state="in conflict")


def _covered_found_as_gap(seeds: Sequence[SeedCase], matches: Matches) -> Matches:
    seed = _first(seeds, lambda s: s.state == "covered")
    return _change(matches, seed.seed_id, found_state="partly covered")


def _citation_moved(seeds: Sequence[SeedCase], matches: Matches) -> Matches:
    seed = _first(seeds, lambda s: s.state != "not covered" and bool(s.clauses))
    return _change(matches, seed.seed_id, cited=((seed.clauses[0][0], "99.9"),))


def _match_dropped(seeds: Sequence[SeedCase], matches: Matches) -> Matches:
    seed = _first(seeds, lambda s: s.state in GAP_STATES)
    return [m for m in matches if m.seed_id != seed.seed_id]


PLANTS: tuple[Plant, ...] = (
    Plant(
        "gap-found-as-covered",
        "A seeded partly covered case is found covered",
        ("seeded_gaps_found", "same_state"),
        _gap_found_as_covered,
    ),
    Plant(
        "state-changed-between-gaps",
        "A seeded partly covered case is found in conflict",
        ("same_state",),
        _state_changed_between_gaps,
    ),
    Plant(
        "covered-found-as-gap",
        "A seeded covered case is found partly covered",
        ("same_state", "false_gaps"),
        _covered_found_as_gap,
    ),
    Plant(
        "citation-moved",
        "A seeded case cites a clause the labels do not name",
        ("wrong_citations",),
        _citation_moved,
    ),
    Plant(
        "match-dropped",
        "A seeded gap has no match at all",
        ("seeded_gaps_found", "same_state"),
        _match_dropped,
    ),
)


def _fell(clean: Report, planted: Report) -> list[str]:
    fell = []
    for measure in MEASURES:
        for scope in SCOPES:
            before = count_of(clean, measure, scope).numerator
            after = count_of(planted, measure, scope).numerator
            worse = after > before if measure in LOWER_IS_BETTER else after < before
            if worse and measure not in fell:
                fell.append(measure)
    return fell


def run_plants(
    seeds: Sequence[SeedCase], *, plants: Sequence[Plant] | None = None
) -> list[PlantResult]:
    """Put each plant into matches that score in full and see which measures fall.

    Args:
        seeds: The seeds.
        plants: The plants to run; every plant of this module by default.

    Returns:
        One result per plant, in order.
    """
    clean = measure_seeds(seeds, perfect_matches(seeds))
    results = []
    for plant in PLANTS if plants is None else plants:
        planted = measure_seeds(seeds, plant.apply(seeds, perfect_matches(seeds)))
        results.append(PlantResult(plant.name, _fell(clean, planted), list(plant.degrades)))
    return results


def _read_run(folder: Path) -> tuple[str, list[MatchRow]]:
    index = folder / "bundle.json"
    try:
        run = json.loads(index.read_text(encoding="utf-8")).get("run", "")
    except (OSError, ValueError, AttributeError) as exc:
        raise MeasureInputError(f"The bundle index {index} cannot be read: {exc}") from exc
    return str(run), read_seed_matches(folder / "seed_matches.jsonl")


def _print_report(report: Report) -> None:
    for line in report_lines(report):
        print(line)
    if report.unmatched:
        print(
            f"seeds with no match: {len(report.unmatched)} of {report.total_seeds} "
            f"({', '.join(report.unmatched)})"
        )
    if report.uncompared:
        print(
            f"citations where the seed names no clause: {len(report.uncompared)} "
            f"({', '.join(report.uncompared)})"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Print the measures of a bundle, or run the planted faults.

    Args:
        argv: The command line without the program name.

    Returns:
        0 on success; 1 when a planted fault is missed, or when a seed has no match in a run that
        may not leave one (a recorded or replayed bundle, or any run under ``--require-all``);
        2 when an input cannot be read or does not agree with the seeds file, including a match
        placed on another obligation than its seed's provision.
    """
    parser = argparse.ArgumentParser(description="Measure a policy assessment's seed matches.")
    parser.add_argument("bundle", nargs="?", type=Path, help="a bundle folder")
    parser.add_argument(
        "--seed-matches", type=Path, help="a seed matches file, in place of a folder"
    )
    parser.add_argument("--seeds", type=Path, help="the seeds file, if not the repository's")
    parser.add_argument("--require-all", action="store_true", help="fail when a seed has no match")
    parser.add_argument("--selftest", action="store_true", help="run the planted faults")
    args = parser.parse_args(argv)
    if not (args.bundle or args.seed_matches or args.selftest):
        parser.error("give a bundle folder, --seed-matches or --selftest")
    try:
        seeds = read_seeds(args.seeds) if args.seeds else read_seeds()
        if args.selftest:
            results = run_plants(seeds, plants=PLANTS)
            for result in results:
                print(result.line())
            caught = sum(1 for r in results if r.caught)
            print(f"planted faults caught: {caught} of {len(results)}")
            return 0 if caught == len(results) else 1
        if args.seed_matches:
            run, matches = None, read_seed_matches(args.seed_matches)
        else:
            run, matches = _read_run(args.bundle)
        report = measure_seeds(seeds, matches)
    except (MeasureInputError, SeedFileError) as exc:
        print(exc, file=sys.stderr)
        return 2
    _print_report(report)
    strict = args.require_all or (run is not None and run != "fake")
    return 1 if strict and report.unmatched else 0


if __name__ == "__main__":
    sys.exit(main())
