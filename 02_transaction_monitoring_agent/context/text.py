"""The word-for-word comparison that the quote check uses."""

from __future__ import annotations

import re
import unicodedata

_QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"'})


def normalise(text: str) -> str:
    """Put a text in the one form that word-for-word comparison uses.

    The steps run in this order: Unicode NFC, curly quotes and apostrophes straightened, each run
    of white space collapsed to one space, the ends trimmed, then one trailing full stop removed.
    Case is kept.

    Args:
        text: Any text.

    Returns:
        The normalised text.
    """
    straight = unicodedata.normalize("NFC", text).translate(_QUOTES)
    return " ".join(straight.split()).removesuffix(".")


def contains_word_for_word(needle: str, haystack: str | None) -> bool:
    """Say whether a quoted text lies inside another text, word for word.

    Both texts are normalised first. A match that starts or ends in the middle of a word does not
    count, because a quote cut through a word is not the text of the row.

    Args:
        needle: The quote.
        haystack: The text of the row, or None when the row was not found.

    Returns:
        True when the normalised needle is not empty and lies in the normalised haystack at word
        boundaries.
    """
    if haystack is None:
        return False
    wanted = normalise(needle)
    if not wanted:
        return False
    start = r"(?<!\w)" if re.match(r"\w", wanted) else ""
    end = r"(?!\w)" if re.search(r"\w$", wanted) else ""
    return re.search(start + re.escape(wanted) + end, normalise(haystack)) is not None
