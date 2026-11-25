"""The file that keeps each experiment's counts, and the check that ties the README's table to it.

The file holds, for every experiment, its name, its LangSmith id, the agent, the dataset, the
repetition, when it ran and the seven measures as counts. It holds nothing about the account that
ran it: no usage, no limit and no cost, and a key it does not define is refused when it is read.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .evaluators import MEASURE_KEYS

RESULTS_FILE = Path(__file__).resolve().parent / "data" / "experiments.json"
ENTRY_KEYS = frozenset(
    {
        "name",
        "experiment_id",
        "agent",
        "dataset",
        "repetition",
        "ran_at",
        "examples",
        "failed_examples",
        "model",
        "effort",
        "prompt_version",
        "measures",
    }
)
FIGURE_KEYS = frozenset({"numerator", "denominator", "population"})
MEASURE_LABELS = {
    "Obligations found": "obligations_found",
    "Invented obligations": "invented_obligations",
    "Quotes word for word": "quotes_word_for_word",
    "Deadlines as written": "deadlines_as_written",
    "Deadlines matched": "deadlines_matched",
    "Paragraph recall": "paragraph_recall",
    "Paragraph precision": "paragraph_precision",
}
"""How the README's spread table names each measure at the start of a row."""
AGENT_WORDS = {"starter": "Starter's agent", "engine": "This engine"}
"""How the README's spread table names each agent in a column heading."""
COLUMN = re.compile(r"(Starter's agent|This engine), (?:run (\d+)|whole document)")


class ExperimentFileError(Exception):
    """The experiments file cannot be read, or holds something it must not."""


class DuplicateExperimentError(ExperimentFileError):
    """The file already holds an experiment of this agent, dataset and repetition."""


@dataclass(frozen=True)
class Figure:
    """One measure's total as two counts and what the denominator counts."""

    numerator: int
    denominator: int
    population: str

    @property
    def text(self) -> str:
        """The counts as the README writes them: ``37 of 39``, or ``none in scope``."""
        if self.denominator == 0:
            return "none in scope"
        return f"{self.numerator} of {self.denominator}"


@dataclass(frozen=True)
class ExperimentEntry:
    """One experiment as the file keeps it."""

    name: str
    experiment_id: str
    agent: str
    dataset: str
    repetition: int
    ran_at: str
    examples: int
    failed_examples: tuple[str, ...]
    model: str
    effort: str | None
    prompt_version: str
    measures: dict[str, Figure]

    def to_json(self) -> dict[str, Any]:
        """The entry as the JSON the file holds."""
        return {
            "name": self.name,
            "experiment_id": self.experiment_id,
            "agent": self.agent,
            "dataset": self.dataset,
            "repetition": self.repetition,
            "ran_at": self.ran_at,
            "examples": self.examples,
            "failed_examples": list(self.failed_examples),
            "model": self.model,
            "effort": self.effort,
            "prompt_version": self.prompt_version,
            "measures": {
                key: {
                    "numerator": f.numerator,
                    "denominator": f.denominator,
                    "population": f.population,
                }
                for key, f in self.measures.items()
            },
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ExperimentEntry:
        """Read an entry from the file's JSON.

        Args:
            data: One object of the file's list.

        Returns:
            The entry.

        Raises:
            ExperimentFileError: If a key is missing or not defined, or a count is not a count.
        """
        name = data.get("name", "an entry")
        extra, lacking = set(data) - ENTRY_KEYS, ENTRY_KEYS - set(data)
        if extra or lacking:
            bad = ", ".join(f"'{k}'" for k in sorted(extra | lacking))
            raise ExperimentFileError(f"{name} has a key the file does not define or lacks: {bad}.")
        if set(data["measures"]) != set(MEASURE_KEYS):
            raise ExperimentFileError(f"{name} does not hold exactly the seven measures.")
        measures = {}
        for key in MEASURE_KEYS:
            raw = data["measures"][key]
            if set(raw) != FIGURE_KEYS:
                raise ExperimentFileError(f"{name}: {key} must hold exactly {sorted(FIGURE_KEYS)}.")
            n, d = raw["numerator"], raw["denominator"]
            if not (isinstance(n, int) and isinstance(d, int) and 0 <= n <= d):
                raise ExperimentFileError(f"{name}: {key} holds {n} of {d}, which is not a count.")
            measures[key] = Figure(n, d, raw["population"])
        return cls(
            name=data["name"],
            experiment_id=data["experiment_id"],
            agent=data["agent"],
            dataset=data["dataset"],
            repetition=data["repetition"],
            ran_at=data["ran_at"],
            examples=data["examples"],
            failed_examples=tuple(data["failed_examples"]),
            model=data["model"],
            effort=data["effort"],
            prompt_version=data["prompt_version"],
            measures=measures,
        )

    @property
    def kind(self) -> tuple[str, str, int]:
        """What the experiment is: the agent, the dataset and the repetition."""
        return self.agent, self.dataset, self.repetition


def read_entries(path: Path = RESULTS_FILE) -> list[ExperimentEntry]:
    """Read every experiment the file holds.

    Args:
        path: The experiments file.

    Returns:
        The entries in the order they were written; none when the file does not exist.

    Raises:
        ExperimentFileError: If the file is not JSON, lacks ``experiments`` or holds an entry
            that is not as defined.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExperimentFileError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {"experiments"}:
        raise ExperimentFileError(f"{path} must hold one object with the list 'experiments'.")
    return [ExperimentEntry.from_json(item) for item in data["experiments"]]


def append_entry(path: Path, entry: ExperimentEntry) -> None:
    """Add one experiment to the file, at once, so a stopped run keeps what it made.

    Args:
        path: The experiments file.
        entry: The experiment that has finished.

    Raises:
        DuplicateExperimentError: If the file holds this agent, dataset and repetition already.
        ExperimentFileError: If the file cannot be read.
    """
    entries = read_entries(path)
    if any(e.kind == entry.kind for e in entries):
        agent, dataset, repetition = entry.kind
        raise DuplicateExperimentError(
            f"The file already holds {agent}, {dataset}, repetition {repetition}."
        )
    body = json.dumps({"experiments": [e.to_json() for e in [*entries, entry]]}, indent=2)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(body + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def column_title(entry: ExperimentEntry) -> str:
    """Return the heading the README's spread table gives an experiment's column.

    Args:
        entry: The experiment.

    Returns:
        ``Starter's agent, run 2`` for a repetition on the sections, ``This engine, whole
        document`` for the one run on the document.
    """
    words = AGENT_WORDS[entry.agent]
    if entry.dataset == "document":
        return f"{words}, whole document"
    return f"{words}, run {entry.repetition}"


def _kind_of(title: str) -> tuple[str, str, int] | None:
    """Read a column heading back into the agent, dataset and repetition it stands for."""
    found = COLUMN.fullmatch(title.replace("\u2019", "'"))
    if found is None:
        return None
    agent = next(k for k, words in AGENT_WORDS.items() if words == found[1])
    if found[2] is None:
        return agent, "document", 1
    return agent, "sections", int(found[2])


def _spread_tables(readme: str) -> list[list[list[str]]]:
    """Every table whose header starts with Measure and then names an agent's run."""
    lines, tables, at = readme.splitlines(), [], 0
    while at < len(lines):
        header = _cells(lines[at]) if lines[at].startswith("|") else []
        if len(header) > 1 and header[0] == "Measure" and _kind_of(header[1]):
            rows = [header]
            at += 1
            while at < len(lines) and lines[at].startswith("|"):
                cells = _cells(lines[at])
                if not all(set(c) <= set("-: ") for c in cells):
                    rows.append(cells)
                at += 1
            tables.append(rows)
        else:
            at += 1
    return tables


def spread_problems(readme: str, entries: Sequence[ExperimentEntry]) -> list[str]:
    """Name every place where the README's spread table and the experiments file disagree.

    The spread table has the first header cell ``Measure`` and one further header cell for each
    experiment, worded by ``column_title``. Each row starts with a measure's name, and each cell
    holds that experiment's counts as ``N of M``. A column is tied to its entry by agent, dataset
    and repetition. The README must also name each experiment and give its LangSmith id, in the list
    under the table. The file and the table must both be empty or both hold every experiment.

    Args:
        readme: The README's text.
        entries: The experiments in the file.

    Returns:
        One sentence for each difference; empty when the table and the file agree.
    """
    tables = _spread_tables(readme)
    if len(tables) > 1:
        return ["The README has more than one spread table."]
    if not tables:
        if entries:
            noun = "entry" if len(entries) == 1 else "entries"
            return [
                f"experiments.json holds {len(entries)} {noun} and the README has no spread table."
            ]
        return []
    if not entries:
        return ["The README has a spread table and experiments.json holds no entry."]
    header, *rows = tables[0]
    by_kind = {e.kind: e for e in entries}
    kinds = [_kind_of(c) for c in header[1:]]
    problems = [
        f"README: the column '{title}' names no experiment in experiments.json."
        for title, kind in zip(header[1:], kinds, strict=True)
        if kind not in by_kind
    ]
    problems += [
        f"README: the column '{title}' appears more than once."
        for title in dict.fromkeys(header[1:])
        if header[1:].count(title) > 1
    ]
    problems += [
        f"experiments.json: {e.name} has no column in the README's table."
        for kind, e in by_kind.items()
        if kind not in kinds
    ]
    for label, key in MEASURE_LABELS.items():
        found = [r for r in rows if r[0].startswith(label)]
        if len(found) != 1:
            problems.append(f"README: the spread table has no row for '{label}'.")
            continue
        if len(found[0]) - 1 != len(kinds):
            problems.append(
                f"README: the row for '{label}' holds {len(found[0]) - 1} of the "
                f"{len(kinds)} figures it needs."
            )
            continue
        for title, kind, cell in zip(header[1:], kinds, found[0][1:], strict=True):
            if kind in by_kind and cell != by_kind[kind].measures[key].text:
                problems.append(
                    f"README: '{label}', {title}, says {cell}; "
                    f"experiments.json holds {by_kind[kind].measures[key].text}."
                )
    for e in entries:
        for what, text in (("name", e.name), ("LangSmith id", e.experiment_id)):
            if text not in readme:
                problems.append(f"README: the list under the table lacks the {what} of {text}.")
    return problems
