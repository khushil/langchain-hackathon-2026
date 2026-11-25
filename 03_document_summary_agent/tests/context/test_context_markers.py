"""Tests of the obligation-marker function: the starter's four markers, found as whole words."""

import pytest

from context.markers import MARKERS, marker_in, markers_in
from context.reader import read_document

DOCUMENT = read_document("PS26-4")
PARAGRAPHS = [p for section in DOCUMENT.sections for p in section.paragraphs]

# The first whole-document run of this document, as the notebook printed it: the 23 paragraphs
# that were closed as holding no fact, and so the 25 that held an obligation fact.
FIRST_RUN_NO_FACT = {
    *(f"1.{n}" for n in range(1, 6)),
    *(f"2.{n}" for n in range(1, 4)),
    *(f"3.{n}" for n in range(1, 6)),
    "4.4",
    "7.4",
    "7.5",
    "8.4",
    "9.2",
    "9.3",
    "9.4",
    "10.1",
    "10.2",
    "10.3",
}
FIRST_RUN_OBLIGATION = {p.number for p in PARAGRAPHS} - FIRST_RUN_NO_FACT


def test_the_four_markers_and_the_plural_of_the_third_are_the_list():
    assert MARKERS == ("must", "shall", "is required to", "are required to", "will need to")


@pytest.mark.parametrize(
    ("text", "marker"),
    [
        ("Contracts must be updated.", "must"),
        ("A firm shall notify the FSOA.", "shall"),
        ("The board is required to approve the list.", "is required to"),
        ("Small firms are required to notify the FSOA.", "are required to"),
        ("Each group will need to show its arrangements.", "will need to"),
    ],
)
def test_each_marker_is_found_and_named_in_lower_case(text, marker):
    assert marker_in(text) == marker
    assert markers_in(text) == [marker]


@pytest.mark.parametrize(
    ("text", "marker"),
    [
        ("MUST be done", "must"),
        ("Must be done", "must"),
        ("It Is Required To be done", "is required to"),
        ("It is  required\nto be done", "is required to"),
        ("(must)", "must"),
        ("it must, however", "must"),
        ("A firm mustn't delay.", "must"),
        ("A firm MUSTN'T delay.", "must"),
        ("A firm mustn\u2019t delay.", "must"),
        ("A firm shan't delay.", "shall"),
        ("A firm shan\u2019t delay.", "shall"),
    ],
)
def test_a_marker_matches_in_any_case_across_white_space_and_punctuation(text, marker):
    assert marker_in(text) == marker


@pytest.mark.parametrize(
    "text",
    [
        "The mustard is yellow.",
        "Mustang",
        "The shallow end.",
        "Marshall Islands",
        "The mustnt rule",
        "Bishan't",
        "Firms should notify the FSOA.",
        "A firm may notify the FSOA.",
        "We expect firms to notify the FSOA.",
        "A firm can notify the FSOA.",
        "A firm is required.",
        "A firm needs to act and is required by law.",
        "A firm will need two days.",
        "",
    ],
)
def test_a_word_that_only_contains_a_marker_and_the_second_rules_words_are_no_marker(text):
    assert marker_in(text) is None
    assert markers_in(text) == []


def test_markers_in_gives_each_marker_once_in_the_order_it_first_appears():
    text = "Firms shall act. They must act. A firm must act. A group will need to act and must act."
    assert markers_in(text) == ["shall", "must", "will need to"]
    assert marker_in(text) == "shall"


def test_the_document_has_forty_eight_paragraphs_and_twenty_three_carry_a_marker():
    assert len(PARAGRAPHS) == 48
    marked = {p.number for p in PARAGRAPHS if marker_in(p.text)}
    assert len(marked) == 23
    assert {m for p in PARAGRAPHS for m in markers_in(p.text)} == {"must"}


def test_of_the_paragraphs_closed_as_no_fact_in_the_first_run_only_nine_three_has_a_marker():
    assert len(FIRST_RUN_NO_FACT) == 23
    marked_without_fact = {
        p.number for p in PARAGRAPHS if p.number in FIRST_RUN_NO_FACT and marker_in(p.text)
    }
    assert marked_without_fact == {"9.3"}


def test_of_the_paragraphs_holding_an_obligation_in_the_first_run_only_three_have_no_marker():
    assert len(FIRST_RUN_OBLIGATION) == 25
    unmarked_with_fact = {
        p.number for p in PARAGRAPHS if p.number in FIRST_RUN_OBLIGATION and not marker_in(p.text)
    }
    assert unmarked_with_fact == {"2.5", "6.6", "9.1"}
