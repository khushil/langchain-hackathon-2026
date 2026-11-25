"""The home page's answer: what waits for a reviewer across the workflows, from one object."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fsi_common.app.pages import MAX_TILES, Answer, Tile
from fsi_common.app.topics import TopicPlugin

NOT_AVAILABLE = "Not available"
ALL_TILE_LABEL = "Waiting for a reviewer"


class WaitingCountError(ValueError):
    """A topic gave a waiting count that cannot be true."""


@dataclass(frozen=True)
class HomeEntry:
    """One workflow as the home page counts it: where its list is and what waits in it.

    A workflow whose process did not answer is ``reachable=False``; it has no count, and its
    list's address is None when it never said where that is.
    """

    title: str
    href: str | None
    noun: str
    waiting: int | None
    reachable: bool = True
    starting: bool = False


def _plural(count: int, noun: str) -> str:
    """Write a count and its noun: "1 brief", "2 briefs", "2 batches", "2 queries"."""
    if count == 1:
        return f"{count} {noun}"
    if noun.endswith(("s", "x", "z", "ch", "sh")):
        return f"{count} {noun}es"
    if noun.endswith("y") and noun[-2:-1] not in {"a", "e", "i", "o", "u", ""}:
        return f"{count} {noun[:-1]}ies"
    return f"{count} {noun}s"


def _joined(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


@dataclass(frozen=True)
class HomeSummary:
    """Every workflow's waiting count; the sentence and the tiles are both made from it."""

    entries: tuple[HomeEntry, ...]

    @property
    def total(self) -> int:
        """The items waiting across the workflows that gave a count."""
        return sum(e.waiting or 0 for e in self.entries)

    def sentence(self) -> str:
        """Say what waits for a reviewer, then which workflows could not say."""
        counted = [e for e in self.entries if e.reachable and e.waiting is not None]
        by_noun: dict[str, int] = {}
        for entry in counted:
            by_noun[entry.noun] = by_noun.get(entry.noun, 0) + (entry.waiting or 0)
        waiting = [(noun, n) for noun, n in by_noun.items() if n]
        sentences = []
        if waiting:
            one = len(waiting) == 1 and waiting[0][1] == 1
            parts = [_plural(n, noun) for noun, n in waiting]
            sentences.append(f"{_joined(parts)} {'is' if one else 'are'} waiting for a reviewer.")
        elif counted:
            nothing = f"No {next(iter(by_noun))}" if len(by_noun) == 1 else "Nothing"
            sentences.append(f"{nothing} is waiting for a reviewer.")
        silent = [e.title for e in self.entries if e.reachable and e.waiting is None]
        if silent:
            sentences.append(f"{_joined(silent)} cannot say what is waiting.")
        lost = [e.title for e in self.entries if not e.reachable and not e.starting]
        if lost:
            sentences.append(f"{_joined(lost)} could not be reached.")
        again = [e.title for e in self.entries if not e.reachable and e.starting]
        if again:
            sentences.append(
                f"{_joined(again)} {'is' if len(again) == 1 else 'are'} starting again."
            )
        return " ".join(sentences)

    def tiles(self) -> tuple[Tile, ...]:
        """Give each workflow a tile with its count and its list's address.

        More workflows than a page may show as tiles are shown as one tile with the total, and
        every workflow stays in the list below.
        """
        if len(self.entries) > MAX_TILES:
            return (
                Tile(
                    label=ALL_TILE_LABEL,
                    value=str(self.total),
                    status="needs_person" if self.total else "normal",
                ),
            )
        return tuple(
            Tile(
                label=e.title,
                value=NOT_AVAILABLE if e.waiting is None else str(e.waiting),
                status="needs_person" if e.waiting else "normal",
                title=f"Open the list of {e.title}" if e.href else "",
                href=e.href,
            )
            for e in self.entries
        )

    def answer(self) -> Answer:
        """Return the page's sentence and tiles."""
        return Answer(sentence=self.sentence(), tiles=self.tiles())


def summarise_home(topics: Sequence[TopicPlugin]) -> HomeSummary:
    """Ask each topic what waits for a reviewer.

    Args:
        topics: The topics served.

    Returns:
        The counts, in the order the topics are served.

    Raises:
        WaitingCountError: If a topic gives a count below nought.
    """
    entries = []
    for topic in topics:
        waiting = topic.waiting()
        if waiting is not None and waiting < 0:
            raise WaitingCountError(f"The waiting count of {topic.title} cannot be below nought.")
        entries.append(HomeEntry(topic.title, topic.list_href, topic.waiting_noun, waiting))
    return HomeSummary(tuple(entries))
