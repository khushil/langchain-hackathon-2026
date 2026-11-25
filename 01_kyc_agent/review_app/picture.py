"""The picture of a batch: each application against each list entry, each screening marked.

It is drawn from the run's state: the screening facts, the reasons the screenings with no fact
have, the open questions and the engine's own accounting. Every screening is in it once, and the
count beside it says how many of the screenings read are accounted for.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from review_app.run_data import RunData, read_run_data
from review_app.wording import LISTS
from utils.kyc_state import KycState

KEY_WORDS = (
    ("settled", "Settled by the checks"),
    ("answered", "Answered by a person"),
    ("needs", "Needs a person"),
    ("near", "Near match, needs a person"),
    ("kept", "Kept as a fact"),
    ("none", "No likeness"),
    ("not_screened", "Not screened"),
)
"""The kinds of mark in the order the key lists them, each with the word the key gives it."""
WORDS = dict(KEY_WORDS)


@dataclass(frozen=True)
class EntryKey:
    """One list entry, a column of the picture, by number."""

    number: int
    list: str
    anchor_part: str
    name: str
    detail: str

    @property
    def list_label(self) -> str:
        """The list the entry is on, in words."""
        return LISTS[self.list]


@dataclass(frozen=True)
class PictureCell:
    """One screening: an application against an entry."""

    anchor_part: str
    state: str
    detail: str

    @property
    def word(self) -> str:
        """The mark's word."""
        return WORDS[self.state]


@dataclass(frozen=True)
class PictureRow:
    """One application and its fourteen screenings."""

    customer_id: str
    name: str | None
    href: str
    cells: tuple[PictureCell, ...]


@dataclass(frozen=True)
class Picture:
    """The batch drawn: rows, columns, and the count that closes."""

    rows: tuple[PictureRow, ...]
    entries: tuple[EntryKey, ...]
    total: int
    accounted: int
    with_facts: int
    without_facts: int

    @property
    def key(self) -> tuple[tuple[str, str], ...]:
        """The marks the picture uses, each with its word, so a reader can tell them apart."""
        used = {cell.state for row in self.rows for cell in row.cells}
        return tuple((kind, word) for kind, word in KEY_WORDS if kind in used)

    @property
    def count(self) -> str:
        """Say how many screenings read are accounted for."""
        return (
            f"{self.accounted} of {self.total} screenings accounted for: "
            f"{self.with_facts} kept as facts and {self.without_facts} with no likeness"
        )


def _state(data: RunData, anchor: str, settled: Mapping[str, str], asked: dict) -> PictureCell:
    part = anchor.partition("/")[2]
    fact = next((f for f in data.facts.values() if f.subject.anchor == anchor), None)
    if fact is None:
        reason = data.reasons.get(anchor, "")
        state = "not_screened" if reason.startswith("Not screened") else "none"
        return PictureCell(part, state, reason or "No reason is held for this screening.")
    attributes = fact.attributes
    score = f"The names score {attributes['name_score']}"
    about = f"{score} against {attributes['entry_name']}"
    if attributes["outcome"] == "settled":
        return PictureCell(part, "settled", f"Settled by the checks: {attributes['settled_by']}")
    question = asked.get(anchor)
    if question is None:
        return PictureCell(
            part, "kept", f"{about}. Kept as a fact; another entry settles the application."
        )
    if question.id in settled:
        return PictureCell(part, "answered", f"{about}. {settled[question.id]}")
    state = "near" if attributes["strength"] == "near" else "needs"
    return PictureCell(part, state, f"{about}. {attributes['why_unsettled']}")


def build_picture(
    state: KycState, *, settled: Mapping[str, str], href_for: Callable[[str], str]
) -> Picture:
    """Draw a batch from a run's state.

    Args:
        state: The run's state.
        settled: How each question a person has settled was settled, by question id; the others
            are drawn as waiting.
        href_for: Gives the address of an application's page from its customer id.

    Returns:
        The picture, with the count of screenings the engine accounted for.
    """
    data = read_run_data(state)
    asked = {
        q.about.anchor: q for q in data.questions.values() if q.about.anchor.startswith("pair:")
    }
    entries = tuple(
        EntryKey(n, e.list, e.anchor_part, e.name, e.detail) for n, e in enumerate(data.entries, 1)
    )
    rows = tuple(
        PictureRow(
            customer_id=c,
            name=data.names.get(c),
            href=href_for(c),
            cells=tuple(
                _state(data, f"pair:{c}/{e.anchor_part}", settled, asked) for e in data.entries
            ),
        )
        for c in data.customers
    )
    accounting = data.screenings
    total = len(rows) * len(entries)
    return Picture(
        rows=rows,
        entries=entries,
        total=total,
        accounted=(len(accounting.with_facts) + len(accounting.without_facts)) if accounting else 0,
        with_facts=len(accounting.with_facts) if accounting else 0,
        without_facts=len(accounting.without_facts) if accounting else 0,
    )
