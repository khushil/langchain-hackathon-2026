"""The measure every code evaluator reports: a key, two counts and the population counted."""

from collections.abc import Iterable
from dataclasses import dataclass


class MeasureError(Exception):
    """A measure was built or combined in a way that would give a meaningless score."""


@dataclass(frozen=True)
class Measure:
    """One measure over one population, as counts.

    A denominator of zero means nothing was in scope; the measure then has no score, and it is never
    shown as 0 or 100 per cent.
    """

    key: str
    numerator: int
    denominator: int
    population: str
    lower_is_better: bool = False

    def __post_init__(self) -> None:
        if self.numerator < 0 or self.denominator < 0:
            raise MeasureError(
                f"{self.key}: a count is negative ({self.numerator} of {self.denominator})"
            )
        if self.numerator > self.denominator:
            raise MeasureError(
                f"{self.key}: the numerator {self.numerator} exceeds "
                f"the denominator {self.denominator}"
            )

    @property
    def in_scope(self) -> bool:
        """Whether anything was in scope for this measure."""
        return self.denominator > 0

    @property
    def score(self) -> float | None:
        """The share numerator over denominator, or None when nothing was in scope."""
        return self.numerator / self.denominator if self.in_scope else None

    @property
    def is_full(self) -> bool:
        """Whether the measure is at its best: every item found, or none invented."""
        if not self.in_scope:
            return False
        return self.numerator == (0 if self.lower_is_better else self.denominator)

    def line(self) -> str:
        """The measure as one line of text, with its counts and its population."""
        if not self.in_scope:
            return f"{self.key}: none in scope ({self.population})"
        return f"{self.key}: {self.numerator} of {self.denominator} {self.population}"


def sum_measures(measures: Iterable[Measure]) -> Measure:
    """Add measures of one key and one population.

    Args:
        measures: Measures to add, such as one per section.

    Returns:
        The measure with the counts added.

    Raises:
        MeasureError: If the input is empty or mixes keys or populations.
    """
    items = list(measures)
    if not items:
        raise MeasureError("nothing to add")
    first = items[0]
    if any(m.key != first.key for m in items):
        raise MeasureError("measures to add must share one key")
    if any(m.population != first.population for m in items):
        raise MeasureError(f"{first.key}: measures to add have different populations")
    return Measure(
        first.key,
        sum(m.numerator for m in items),
        sum(m.denominator for m in items),
        first.population,
        first.lower_is_better,
    )
