"""The obligation markers of the starter's definition, found in a paragraph by plain code."""

from __future__ import annotations

import re

MARKERS = ("must", "shall", "is required to", "are required to", "will need to")
"""The words that mark an obligation.

The starter's definition marks an obligation by "must", "shall", "is required to" or "will need to".
"are required to" is the plural of the third, so a paragraph that says it of several firms is not
missed. "should", "may", "we expect" and "can" are not markers.
"""

_FOUND = re.compile(
    r"(?<!\w)(must(?:n['\u2019]t)?|shall|shan['\u2019]t|(?:is|are)\s+required\s+to"
    r"|will\s+need\s+to)(?!\w)",
    re.IGNORECASE,
)


def _name(found: str) -> str:
    """Return a marker as the list names it: lower case, single spaces, a negative as its word."""
    word = " ".join(found.lower().split())
    if word.startswith("mustn"):
        return "must"
    return "shall" if word.startswith("shan") else word


def markers_in(text: str) -> list[str]:
    """Return the obligation markers a text holds, each once, in the order they first appear.

    A marker is matched as whole words, in any case, with any white space between its words, so
    "mustard" and "shallow" hold none. "mustn't" and "shan't" are the negatives of "must" and
    "shall" and are returned as those words. Each is returned in lower case with single spaces.

    Args:
        text: A paragraph's text.

    Returns:
        The markers found; empty when the text holds none.
    """
    return list(dict.fromkeys(_name(match) for match in _FOUND.findall(text)))


def marker_in(text: str) -> str | None:
    """Return the first obligation marker a text holds.

    Args:
        text: A paragraph's text.

    Returns:
        The marker in lower case, or None when the text holds none.
    """
    found = markers_in(text)
    return found[0] if found else None
