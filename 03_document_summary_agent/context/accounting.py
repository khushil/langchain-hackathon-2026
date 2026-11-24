"""Close the count of units read against the units that ended with facts or with a reason."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from context.errors import AccountingError
from fsi_common.records import Fact, Source, SourceUnit, UnitAccounting

NO_FACT_REASON = "The section reader found no obligation in this paragraph."
"""The reason recorded for a paragraph that produced no fact."""

TABLE_NO_FACT_REASON = "The row held no field this run reads."
"""The reason recorded for a table row that produced no fact."""


def no_fact_reason(source: Source) -> str:
    """Return the reason a unit of this source gives when it has no fact.

    Args:
        source: The source accounted for.

    Returns:
        The paragraph reason for a document, and the row reason for a table.
    """
    return NO_FACT_REASON if source.kind == "document" else TABLE_NO_FACT_REASON


@dataclass(frozen=True)
class AccountingResult:
    """A source's accounting, the line that states its counts, and facts on units not read."""

    accounting: UnitAccounting
    line: str
    phantom_anchors: list[str]


def account_for_units(
    source: Source,
    expected: Sequence[SourceUnit],
    held: Iterable[SourceUnit],
    facts: Iterable[Fact],
    *,
    reason: str = NO_FACT_REASON,
) -> AccountingResult:
    """Account for every unit a source was read into, or fail naming the units that are missing.

    The units expected are those a fresh read of the source gives; the units held are those the
    run's state holds. Every expected unit must be held, and each ends with facts or with
    ``reason``. Facts that cite an anchor that is not an expected unit (a model's invented
    paragraph) are not counted as units; their anchors are returned so the run can name them.

    Args:
        source: The source accounted for.
        expected: Every unit the source was read into.
        held: The units the state holds for this source.
        facts: Every fact of the run; those of other sources are ignored.
        reason: Why a unit with no fact has none, in plain words.

    Returns:
        The accounting record, the line that states its counts, and the phantom anchors.

    Raises:
        AccountingError: If the source was read into no units, or a unit read is not held, or a
            unit is held that was never read. Every such anchor is named.
    """
    if not expected:
        raise AccountingError(f"Source {source.key} was read into no units.")
    expected_anchors = [unit.anchor for unit in expected]
    held_anchors = {unit.anchor for unit in held}
    missing = [a for a in expected_anchors if a not in held_anchors]
    unexpected = sorted(held_anchors - set(expected_anchors))
    if missing or unexpected:
        parts = []
        if missing:
            parts.append(f"unit(s) read but not held: {', '.join(missing)}")
        if unexpected:
            parts.append(f"unit(s) held but never read: {', '.join(unexpected)}")
        raise AccountingError(
            f"The units of {source.key} do not close: "
            f"{len(expected_anchors) - len(missing)} of {len(expected_anchors)} are held; "
            + "; ".join(parts)
            + ".",
            missing=missing,
            unexpected=unexpected,
        )
    cited = {f.subject.anchor for f in facts if f.subject.source_id == source.id}
    with_facts = [a for a in expected_anchors if a in cited]
    without = [{"anchor": a, "reason": reason} for a in expected_anchors if a not in cited]
    accounting = UnitAccounting.build(
        source_id=source.id,
        units_in=len(expected_anchors),
        with_facts=with_facts,
        without_facts=without,
    )
    line = (
        f"{source.key}: {len(with_facts) + len(without)} of {len(expected_anchors)} units "
        f"accounted for ({len(with_facts)} with facts, {len(without)} without)"
    )
    return AccountingResult(
        accounting=accounting, line=line, phantom_anchors=sorted(cited - set(expected_anchors))
    )
