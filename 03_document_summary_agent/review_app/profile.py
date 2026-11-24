"""The firm profile: the firm and provider facts a brief cites, decided together.

A row of the firm or provider table is not a statement to weigh one fact at a time. The reviewer
reads the profile the brief was written against, confirms or amends it once and gives one reason.
The review route turns that one act into one decision for each fact the profile covers, so the
records stay one decision for each subject.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from fsi_common.records import Decision, Fact

PROFILE_KINDS = ("firm_attribute", "provider_attribute")
"""The kinds of fact read from the firm and provider tables."""


def is_profile(fact: Fact) -> bool:
    """Return whether a fact belongs to the firm profile."""
    return fact.kind in PROFILE_KINDS


@dataclass(frozen=True)
class ProfileDecision:
    """One decision that settles every fact of the profile, as the reviewer made it."""

    decision: Decision
    fact_ids: tuple[str, ...]


def shared_decision(
    fact_ids: Iterable[str], decisions: Mapping[str, Decision | None]
) -> ProfileDecision | None:
    """Return the one decision that covers every given fact, when there is one.

    Args:
        fact_ids: The facts of the profile.
        decisions: The decision each fact stands on, or None for a fact without one.

    Returns:
        The decision and the facts it covered, when every fact has a decision and the decisions
        agree in outcome, reason, wording, reviewer and date; otherwise None.
    """
    ids = tuple(fact_ids)
    found = [decisions.get(fid) for fid in ids]
    if not ids or any(d is None for d in found):
        return None
    first = found[0]
    same = all(
        (d.outcome, d.reason, d.amendment, d.reviewer, d.date)
        == (first.outcome, first.reason, first.amendment, first.reviewer, first.date)
        for d in found
    )
    return ProfileDecision(first, ids) if same else None
