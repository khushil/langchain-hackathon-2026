"""The text comparison rules that every measure shares."""

import re
import unicodedata

_QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"'})
_PARAGRAPH_LINE = re.compile(r"^(\d+\.\d+) (.+)$")
_WORD = re.compile(r"\w+")


def normalise(text: str) -> str:
    """Put a string in the form every comparison uses.

    The steps run in this order: Unicode NFC, curly quotes and apostrophes straightened, each run of
    whitespace collapsed to one space, the ends trimmed, then one trailing full stop removed.
    Case is kept.

    Args:
        text: Any string.

    Returns:
        The normalised string.
    """
    text = unicodedata.normalize("NFC", text).translate(_QUOTES)
    text = " ".join(text.split())
    return text.removesuffix(".")


def is_word_for_word(quote: str, paragraph_text: str | None) -> bool:
    """Say whether a quote is a contiguous part of a paragraph, after normalising both.

    Args:
        quote: The quoted string.
        paragraph_text: The paragraph's line without its number, or None if it does not exist.

    Returns:
        True when the normalised quote is non-empty and lies inside the normalised paragraph.
    """
    if paragraph_text is None:
        return False
    wanted = normalise(quote)
    return bool(wanted) and wanted in normalise(paragraph_text)


def word_set(text: str) -> frozenset[str]:
    """The lower-cased words of a string's normalised form, as a set.

    Args:
        text: Any string.

    Returns:
        The distinct words, where a word is a run of letters, digits or underscores.
    """
    return frozenset(_WORD.findall(normalise(text).lower()))


def paragraph_texts(document_text: str) -> dict[str, str]:
    """Read the numbered paragraphs of a document, in order, each without its number.

    Args:
        document_text: Markdown where a paragraph is one line opening with a number like "7.1".

    Returns:
        Paragraph number to the paragraph's text.
    """
    found: dict[str, str] = {}
    for line in document_text.splitlines():
        match = _PARAGRAPH_LINE.match(line)
        if match:
            found[match.group(1)] = match.group(2)
    return found
