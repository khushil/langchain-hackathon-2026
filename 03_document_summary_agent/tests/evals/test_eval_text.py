"""Tests for the text comparison rules the measures share."""

import pytest

from evals.normalise import (
    is_word_for_word,
    normalise,
    paragraph_texts,
    word_set,
)

PARAGRAPHS = """## 7. Incident reporting

7.1 Firms must submit an initial notification within 4 hours.

7.2 Firms must submit an intermediate report within 72 hours.
"""


def test_normalise_composes_unicode_to_nfc():
    assert normalise("é") == "é"


def test_normalise_straightens_curly_quotes_and_apostrophes():
    assert normalise("‘a’ “b” firm’s") == "'a' \"b\" firm's"


def test_normalise_collapses_whitespace_and_trims():
    assert normalise("  one \n\t two  three  ") == "one two three"


def test_normalise_removes_one_trailing_full_stop_only():
    assert normalise("It ends.") == "It ends"
    assert normalise("It ends..") == "It ends."


def test_normalise_keeps_case_and_inner_full_stops():
    assert normalise("Must. Then Must.") == "Must. Then Must"
    assert normalise("must") != normalise("Must")


def test_normalise_of_empty_text_is_empty():
    assert normalise("") == ""
    assert normalise(" . ") == ""


def test_normalise_follows_the_stated_order_with_a_space_before_the_stop():
    # The stop is removed after trimming, so a space left in front of it stays.
    assert normalise("abc .") == "abc "


@pytest.mark.parametrize(
    ("quote", "paragraph", "expected"),
    [
        ("within 4 hours", "Firms must act within 4 hours.", True),
        ("within four hours", "Firms must act within 4 hours.", False),
        ("firms must act within 4 hours.", "Firms must act within 4 hours.", False),
        ("Firms must act within 4 hours.", "Firms must act within 4 hours.", True),
        ("Firms must act", "Firms must act within 4 hours.", True),
        ("firm’s duty", "The firm's duty applies.", True),
        ("", "Anything at all.", False),
        ("   ", "Anything at all.", False),
        ("a", None, False),
    ],
)
def test_is_word_for_word(quote, paragraph, expected):
    assert is_word_for_word(quote, paragraph) is expected


def test_word_set_lower_cases_and_splits_hyphens():
    assert word_set("Third-party Provider, 5 days") == {"third", "party", "provider", "5", "days"}
    assert word_set("") == frozenset()


def test_paragraph_texts_reads_each_numbered_line_without_its_number():
    assert paragraph_texts(PARAGRAPHS) == {
        "7.1": "Firms must submit an initial notification within 4 hours.",
        "7.2": "Firms must submit an intermediate report within 72 hours.",
    }


def test_paragraph_texts_ignores_headings_and_blank_lines():
    assert paragraph_texts("## 1. Intro\n\nplain line\n") == {}
