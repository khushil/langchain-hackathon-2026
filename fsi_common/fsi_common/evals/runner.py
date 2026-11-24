"""Apply code evaluators to pairs of a reference example and an output, and report each measure."""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .measures import Measure, MeasureError, sum_measures

Evaluator = Callable[[Mapping[str, Any], Any], Sequence[Measure]]


@dataclass
class RunReport:
    """The outcome of one run: the totals per measure, each example's measures and every failure."""

    totals: list[Measure] = field(default_factory=list)
    per_example: list[tuple[str, list[Measure]]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether the run scored something and nothing failed."""
        return not self.failures and bool(self.totals)

    @property
    def exit_code(self) -> int:
        """0 when the run is ok, otherwise 1."""
        return 0 if self.ok else 1

    def render(self, *, per_example: bool = False) -> str:
        """The report as text: one line per measure, then PASS or FAIL with each failure.

        Args:
            per_example: Also list each example's own measures.

        Returns:
            The text, ending in a verdict line.
        """
        count = len(self.per_example)
        noun = "example" if count == 1 else "examples"
        lines = []
        if per_example:
            for name, measures in self.per_example:
                lines.append(name)
                lines.extend(f"  {m.line()}" for m in measures)
        lines.extend(f"{m.line()} ({count} {noun})" for m in self.totals)
        lines.extend(f"FAIL {failure}" for failure in self.failures)
        lines.append("PASS" if self.ok else "FAIL")
        return "\n".join(lines)


def _describe(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def _name(evaluator: Evaluator) -> str:
    return getattr(evaluator, "__name__", repr(evaluator))


def _apply(
    evaluators: Sequence[Evaluator], example: Mapping[str, Any], output: Any, label: str
) -> tuple[list[Measure], list[str]]:
    measures: list[Measure] = []
    failures: list[str] = []
    for evaluator in evaluators:
        try:
            produced = list(evaluator(example, output))
        except (
            Exception
        ) as error:  # any evaluator fault fails the run, and is reported with its cause
            failures.append(f"evaluator {_name(evaluator)} raised on {label}: {_describe(error)}")
            continue
        if not all(isinstance(m, Measure) for m in produced):
            failures.append(
                f"evaluator {_name(evaluator)} on {label} returned something other than measures"
            )
            continue
        measures.extend(produced)
    return measures, failures


def run_evaluators(
    pairs: Iterable[tuple[Mapping[str, Any], Any]],
    evaluators: Sequence[Evaluator],
    *,
    required: Iterable[str] = (),
) -> RunReport:
    """Apply every evaluator to every pair and total each measure.

    Args:
        pairs: Each a reference example (a mapping, named by its `key` if it has one) and the
            output to score.
        evaluators: Functions from an example and an output to measures.
        required: Measure keys that must have something in scope across the run.

    Returns:
        The report. It fails when there are no examples or no evaluators, when an evaluator
        raises, when
        a required measure has nothing in scope or was never produced, and when one key is reported
        with two populations.
    """
    report = RunReport()
    pair_list = list(pairs)
    if not pair_list:
        report.failures.append("no examples were scored")
    if not evaluators:
        report.failures.append("no evaluators were given")
    by_key: dict[str, list[Measure]] = {}
    for index, (example, output) in enumerate(pair_list, start=1):
        label = str(example.get("key", f"example {index}"))
        measures, failures = _apply(evaluators, example, output, label)
        report.failures.extend(failures)
        report.per_example.append((label, measures))
        for measure in measures:
            by_key.setdefault(measure.key, []).append(measure)
    for key, measures in by_key.items():
        try:
            report.totals.append(sum_measures(measures))
        except MeasureError as error:
            report.failures.append(f"{key} could not be totalled: {error}")
    totals = {m.key: m for m in report.totals}
    for key in required:
        if key not in totals:
            report.failures.append(f"{key}: no evaluator produced it")
        elif not totals[key].in_scope:
            report.failures.append(f"{key}: none in scope, so nothing was scored")
    return report
