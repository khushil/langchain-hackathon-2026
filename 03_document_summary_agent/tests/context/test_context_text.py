"""Tests of the word-for-word comparison every check of the context layer shares."""

import pytest
from context.text import contains_word_for_word, normalise


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Firms   must\tsubmit\n a report. ", "Firms must submit a report"),
        ("the firm’s “best” effort", 'the firm\'s "best" effort'),
        ("café", "café"),
        ("ends with two stops..", "ends with two stops."),
        ("Case Is Kept", "Case Is Kept"),
        ("", ""),
    ],
)
def test_normalise_applies_each_rule_in_turn(raw, expected):
    assert normalise(raw) == expected


def test_contains_word_for_word_accepts_a_part_of_the_text():
    paragraph = "Firms must submit an initial notification to the FSOA within 4 hours."
    assert contains_word_for_word("must submit an initial notification", paragraph)
    assert contains_word_for_word("within 4 hours.", paragraph)
    assert contains_word_for_word("within 4 hours", paragraph)


def test_contains_word_for_word_accepts_curly_quotes_and_spacing():
    paragraph = "The firm’s board must  approve the list."
    assert contains_word_for_word("The firm's board must approve", paragraph)


def test_contains_word_for_word_keeps_case():
    assert not contains_word_for_word("firms must submit", "Firms must submit a report.")


def test_contains_word_for_word_refuses_a_paraphrase():
    paragraph = "Firms must submit an initial notification to the FSOA within 4 hours."
    assert not contains_word_for_word("Firms have to send a first notice to the FSOA", paragraph)


def test_contains_word_for_word_refuses_a_cut_through_a_word():
    assert not contains_word_for_word("ust submit", "Firms must submit a report.")
    assert not contains_word_for_word("must submi", "Firms must submit a report.")


def test_contains_word_for_word_refuses_an_empty_needle_and_a_missing_text():
    assert not contains_word_for_word("", "Firms must submit a report.")
    assert not contains_word_for_word("   ", "Firms must submit a report.")
    assert not contains_word_for_word("must", None)


def test_contains_word_for_word_ignores_only_one_trailing_stop():
    assert not contains_word_for_word("must submit a report..", "Firms must submit a report.")
