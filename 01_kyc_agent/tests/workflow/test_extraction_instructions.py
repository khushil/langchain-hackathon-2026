"""What the reader is told: a detail the application does not state is left blank, never guessed."""

from workflow.reading import INSTRUCTIONS


def test_the_reader_is_told_to_give_no_quote_for_a_detail_the_application_does_not_state():
    text = " ".join(INSTRUCTIONS.split())
    assert "closest words" not in text
    assert "empty quote and an empty value" in text


def test_the_reader_is_told_to_decide_nothing():
    assert "Do not decide anything about the customer" in INSTRUCTIONS
