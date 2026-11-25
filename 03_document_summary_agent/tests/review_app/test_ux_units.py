"""The small functions behind the reviewer's pages, tested on their own."""

from __future__ import annotations

import pytest

from context.accounting import NO_FACT_REASON, marked_no_fact_reason
from review_app.context import NO_ANSWER_HELD, plain_error
from review_app.paragraph_map import NO_OBLIGATION_FOUND, plain_reason, settled_by_state
from review_app.source_view import sentence_end

HASH = "ab" * 32


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        ("Send the report.", "Send the report."),
        ("Send the report", "Send the report."),
        ("  Is it due?  ", "Is it due?"),
        ("Do it now!", "Do it now!"),
    ],
)
def test_a_persons_words_end_in_one_mark_that_closes_a_sentence(words, expected):
    assert sentence_end(words) == expected


def test_a_missing_saved_answer_is_said_without_its_hash_or_its_mode():
    text = (
        f"Replay has no recording for request {HASH}. Record it with a live call in mode 'record'."
    )
    assert plain_error(text) == NO_ANSWER_HELD


def test_another_failure_keeps_its_words_and_loses_a_long_identifier():
    assert plain_error(f"Section 7 failed: sha256:{HASH} was not read.") == (
        "Section 7 failed: was not read."
    )
    assert plain_error(None) == "The engine gave no reason."
    assert plain_error("The model did not answer.") == "The model did not answer."


def test_a_reason_the_run_recorded_is_put_in_the_words_a_reviewer_uses():
    assert plain_reason("The section reader found no obligation in this paragraph.") == (
        NO_OBLIGATION_FOUND
    )
    assert plain_reason("The row held no field this run reads.") == (
        "The row held no field this run reads."
    )


def test_a_run_with_no_question_settled_says_none_settled():
    assert settled_by_state({"open_questions": {"question:1": {}}, "decisions": {}}) == {}


def test_the_engines_own_reasons_are_put_in_plain_words_whatever_the_engine_says():
    """The page's patterns follow the engine's wording; if either moves, this fails."""
    assert plain_reason(NO_FACT_REASON) == NO_OBLIGATION_FOUND
    for marker in ("must", "shall", "is required to"):
        said = plain_reason(marked_no_fact_reason(marker))
        assert said == (
            f'The paragraph contains "{marker}", which can mark an obligation, but no obligation '
            "was recorded from it. A question about it is open."
        )


def test_a_failure_reason_starts_with_a_capital_letter():
    assert plain_error("the store was unavailable") == "The store was unavailable"
