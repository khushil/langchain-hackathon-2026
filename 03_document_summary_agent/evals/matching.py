"""Pair predicted obligations with labelled ones, one to one, best overlap first."""

from dataclasses import dataclass

from .normalise import normalise, word_set

MIN_JACCARD = 0.5


@dataclass(frozen=True)
class Predicted:
    """One obligation as a section summary states it."""

    paragraph: str
    evidence: str
    deadline: str | None


@dataclass(frozen=True)
class Labelled:
    """One labelled obligation, with its place in the order of the labelled items."""

    paragraph: str
    evidence: str
    deadline: str | None


def jaccard(first: str, second: str) -> float:
    """The Jaccard index of the word sets of two strings; 0 when both are empty.

    Args:
        first: One string.
        second: Another string.

    Returns:
        A number from 0 to 1.
    """
    a, b = word_set(first), word_set(second)
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _contains(first: str, second: str) -> bool:
    a, b = normalise(first), normalise(second)
    return bool(a) and bool(b) and (a in b or b in a)


def pair_obligations(predicted: list[Predicted], labelled: list[Labelled]) -> dict[int, int]:
    """Pair predicted obligations with labelled ones.

    Two obligations can pair when they cite the same paragraph and either one's normalised evidence
    contains the other's or their word sets have a Jaccard index of at least 0.5. Pairs are made
    one to one, highest index first, ties going to the earlier labelled item and then the earlier
    predicted one.

    Args:
        predicted: The predicted obligations in the summary's order.
        labelled: The labelled obligations in the labels' order.

    Returns:
        Predicted index to labelled index for each pair made.
    """
    candidates = []
    for p_index, p in enumerate(predicted):
        for l_index, label in enumerate(labelled):
            if p.paragraph != label.paragraph:
                continue
            overlap = jaccard(p.evidence, label.evidence)
            if overlap >= MIN_JACCARD or _contains(p.evidence, label.evidence):
                candidates.append((-overlap, l_index, p_index))
    pairs: dict[int, int] = {}
    taken: set[int] = set()
    for _, l_index, p_index in sorted(candidates):
        if p_index in pairs or l_index in taken:
            continue
        pairs[p_index] = l_index
        taken.add(l_index)
    return pairs
