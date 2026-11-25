"""The one rule that turns what the checks found into a proposal."""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple


class Proposed(NamedTuple):
    """What the engine proposes for an application, and whether its checks settled it."""

    settled: bool
    risk_level: str
    decision: str


def decide(
    *, name_checked: bool, sanctions_match: str | None, unsettled: Sequence[str]
) -> Proposed:
    """Propose a risk level and a decision from what the checks found.

    The checks settle an application in two cases only: a sanctions entry with an exact name and
    the same date of birth (high risk, reject), and no likeness to any entry with the name
    established and no question left (low risk, approve). Every other application takes the
    cautious reading, high risk and reject, which is the starter's own reading of a hit, and is
    marked as not settled so that a person answers what remains.

    Args:
        name_checked: Whether the applicant's name passed its check, so that screening could run.
        sanctions_match: The sanctions entry that matched by exact name and date of birth, if any.
        unsettled: What the checks could not settle: screenings and relations, by name.

    Returns:
        The proposal.
    """
    if sanctions_match:
        return Proposed(True, "high", "reject")
    if name_checked and not unsettled:
        return Proposed(True, "low", "approve")
    return Proposed(False, "high", "reject")
