"""Checks that the labels of a list of points run in sequence, so a dropped point is named."""

from __future__ import annotations

import re

_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
_LABEL = re.compile(r"^\(?([A-Za-z]{1,6}|\d{1,3})\)?[.)]?$")


def roman_value(text: str) -> int | None:
    """Return the value of a lower-case Roman numeral, or None when the text is not one.

    Args:
        text: The text, for example ``iv``.

    Returns:
        The value, for example 4.
    """
    if not text or any(c not in _ROMAN for c in text):
        return None
    total = 0
    for index, char in enumerate(text):
        value = _ROMAN[char]
        total += -value if index + 1 < len(text) and _ROMAN[text[index + 1]] > value else value
    return total


def label_core(label: str) -> str | None:
    """Return the bare label of a point: ``(a)`` gives ``a`` and ``12.`` gives ``12``.

    Args:
        label: The label as the text writes it.

    Returns:
        The bare label, or None when the text is not a point label.
    """
    match = _LABEL.match(label.strip())
    return match.group(1) if match else None


def sequence_gap(labels: list[str]) -> tuple[str, str] | None:
    """Find the first break in a run of point labels.

    Letters must run a, b, c; numbers 1, 2, 3; Roman numerals i, ii, iii. A list whose labels
    mix kinds, or use doubled letters such as ``aa``, is not judged: it is irregular, not wrong.

    Args:
        labels: The labels of one list, in order.

    Returns:
        ``(missing, after)`` for the first missing label and the label before it, or None when
        the run is complete or the list is not one this check judges.
    """
    cores = [label_core(label) for label in labels]
    if len(cores) < 2 or any(core is None for core in cores):
        return None
    texts = [core for core in cores if core is not None]
    if all(t.isdigit() for t in texts):
        values = [int(t) for t in texts]
        render = str
    elif all(len(t) == 1 and t.isalpha() and t.islower() for t in texts):
        # A single letter that is also a Roman numeral (i, v, x) is read as a letter here, which
        # is right for a list that has run past h; a list of numerals begins i, ii and is below.
        values = [ord(t) - ord("a") + 1 for t in texts]

        def render(v: int) -> str:
            return chr(ord("a") + v - 1)
    elif all(roman_value(t) is not None for t in texts):
        values = [roman_value(t) or 0 for t in texts]

        def render(v: int) -> str:
            return _to_roman(v)
    else:
        return None
    for before, after in zip(values, values[1:], strict=False):
        if after != before + 1:
            return (render(before + 1), render(before)) if after > before + 1 else None
    return None


def is_regular(labels: list[str]) -> bool:
    """Say whether a list's labels are of a kind the sequence check judges.

    Args:
        labels: The labels of one list.

    Returns:
        True for a list of letters, numbers or Roman numerals; False for any other.
    """
    cores = [label_core(label) for label in labels]
    if any(c is None for c in cores):
        return False
    texts = [c for c in cores if c is not None]
    return (
        all(t.isdigit() for t in texts)
        or all(len(t) == 1 and t.isalpha() and t.islower() for t in texts)
        or all(roman_value(t) is not None for t in texts)
    )


def _to_roman(value: int) -> str:
    pairs = [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for number, text in pairs:
        while value >= number:
            out += text
            value -= number
    return out
