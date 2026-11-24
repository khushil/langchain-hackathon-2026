"""Tests of the plain-code checks run on every obligation fact."""

from context.checks import DEADLINE_CHECK, QUOTE_CHECK, check_deadline, check_quote, checks_for
from sub_agent import Obligation

PARAGRAPH = (
    "Firms must submit an initial notification to the FSOA within 4 hours of classifying an "
    "incident as a major incident, and in any case no later than 24 hours after the incident is "
    "first detected."
)


def _obligation(**changes):
    fields = {
        "requirement": "Notify the FSOA of a major incident",
        "paragraph": "7.1",
        "deadline": "within 4 hours of classifying an incident as a major incident",
        "evidence": "Firms must submit an initial notification to the FSOA within 4 hours",
    }
    return Obligation(**(fields | changes))


def test_quote_check_passes_a_verbatim_quote():
    result = check_quote(_obligation().evidence, PARAGRAPH, anchor="para:7.1")
    assert (result.check, result.outcome) == (QUOTE_CHECK, "pass")
    assert "7.1" in result.detail


def test_quote_check_fails_a_paraphrase_and_says_so():
    quote = "Firms have to send a first notice to the FSOA inside four hours"
    result = check_quote(quote, PARAGRAPH, anchor="para:7.1")
    assert result.outcome == "fail"
    assert "not found word for word" in result.detail


def test_quote_check_fails_when_the_paragraph_is_not_there():
    result = check_quote("Firms must submit", None, anchor="para:99.1")
    assert result.outcome == "fail"
    assert "99.1" in result.detail
    assert "no such paragraph" in result.detail


def test_deadline_check_passes_the_deadline_as_written():
    result = check_deadline(
        "within 4 hours of classifying an incident", PARAGRAPH, anchor="para:7.1"
    )
    assert (result.check, result.outcome) == (DEADLINE_CHECK, "pass")


def test_deadline_check_fails_a_converted_deadline():
    result = check_deadline("4h", PARAGRAPH, anchor="para:7.1")
    assert result.outcome == "fail"
    assert "not found word for word" in result.detail
    assert check_deadline("within 240 minutes", PARAGRAPH, anchor="para:7.1").outcome == "fail"


def test_checks_for_runs_the_quote_check_and_the_deadline_check_when_there_is_a_deadline():
    results = checks_for(_obligation(), PARAGRAPH)
    assert [(r.check, r.outcome) for r in results] == [
        (QUOTE_CHECK, "pass"),
        (DEADLINE_CHECK, "pass"),
    ]


def test_checks_for_runs_only_the_quote_check_when_there_is_no_deadline():
    results = checks_for(_obligation(deadline=None), PARAGRAPH)
    assert [(r.check, r.outcome) for r in results] == [(QUOTE_CHECK, "pass")]


def test_checks_for_an_unknown_paragraph_fails_both_checks():
    results = checks_for(_obligation(paragraph="99.1"), None)
    assert [(r.check, r.outcome) for r in results] == [
        (QUOTE_CHECK, "fail"),
        (DEADLINE_CHECK, "fail"),
    ]
