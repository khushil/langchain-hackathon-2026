"""The firm profile as the review page draws it: the firm and each provider, by attribute."""

from __future__ import annotations

from dataclasses import dataclass

from review_app.naming import Naming
from review_app.review_model import FactState, ReviewModel


@dataclass(frozen=True)
class ProfileRow:
    """One fact of the profile: what it states, in words, and where it stands."""

    fact_id: str
    label: str
    value: str
    state: FactState


@dataclass(frozen=True)
class ProfileGroup:
    """The facts about one firm or one provider."""

    heading: str
    rows: tuple[ProfileRow, ...]


def profile_groups(model: ReviewModel, naming: Naming) -> tuple[ProfileGroup, ...]:
    """Group the profile's facts by the firm or provider they are about, in the brief's order.

    Args:
        model: The review.
        naming: The names of the firms and providers.

    Returns:
        One group for each firm or provider, headed by its name.
    """
    groups: dict[str, list[ProfileRow]] = {}
    for fid in model.profile_ids:
        fact = model.cited[fid].fact
        label, value = naming.profile_line(fact)
        row = ProfileRow(fid, label, value, model.fact_states[fid])
        groups.setdefault(naming.place(fact.subject.anchor), []).append(row)
    return tuple(ProfileGroup(heading, tuple(rows)) for heading, rows in groups.items())
