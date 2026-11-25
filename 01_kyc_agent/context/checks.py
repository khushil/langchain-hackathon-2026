"""The plain-code checks on what an application's reading and its screening say."""

from __future__ import annotations

from datetime import datetime

from context.rule import decide
from context.text import contains_word_for_word
from fsi_common.records import CheckResult
from tools.screening import name_similarity

QUOTE_CHECK = "quote-verbatim.v1"
"""The check that a fact's quote is word for word in the application it cites."""

NAME_CHECK = "name-verbatim.v1"
"""The check that the name a fact gives is written in the application."""

DATE_CHECK = "date-reads-as.v1"
"""The check that the date as the application writes it reads as the date the fact gives."""

AMOUNT_CHECK = "amount-verbatim.v1"
"""The check that the amount a fact gives is written in the application."""

WORDS_CHECK = "words-verbatim.v1"
"""The check that words a fact gives about a relation are written in the application."""

SCORE_CHECK = "name-score.v1"
"""The check that a screening's score is the starter's measure of the two names."""

DOB_CHECK = "dob-comparison.v1"
"""The check that a screening's comparison of dates of birth is what the two dates give."""

PROPOSAL_CHECK = "proposal-follows-checks.v1"
"""The check that a proposal is what the one rule gives for what the checks found."""

DATE_FORMATS = ("%d %B %Y", "%B %d, %Y", "%B %d %Y", "%Y-%m-%d")
"""The ways the applications write a date, tried in this order."""


def _outcome(name: str, ok: bool, *, passed: str, failed: str) -> CheckResult:
    return CheckResult(
        check=name, outcome="pass" if ok else "fail", detail=passed if ok else failed
    )


def check_quote(quote: str, text: str | None, *, anchor: str) -> CheckResult:
    """Check that a quote is word for word in the application it cites.

    Args:
        quote: The quote the reader gave.
        text: The application's text, or None when it was not found.
        anchor: The application's anchor, for the detail.

    Returns:
        A ``quote-verbatim.v1`` result saying what was compared and what was found.
    """
    where = anchor.partition(":")[2]
    return _outcome(
        QUOTE_CHECK,
        contains_word_for_word(quote, text),
        passed=f"found word for word in the application {where}",
        failed=f"'{quote}' is not found word for word in the application {where}",
    )


def check_name(name: str, text: str | None, *, anchor: str) -> CheckResult:
    """Check that a name is written in the application as the reader gave it.

    Args:
        name: The name the reader gave.
        text: The application's text.
        anchor: The application's anchor.

    Returns:
        A ``name-verbatim.v1`` result.
    """
    where = anchor.partition(":")[2]
    return _outcome(
        NAME_CHECK,
        contains_word_for_word(name, text),
        passed=f"the name '{name}' is written in the application {where}",
        failed=f"the name '{name}' is not written in the application {where}",
    )


def check_words(words: str, label: str, text: str | None, *, anchor: str) -> CheckResult:
    """Check that words a fact gives are written in the application.

    Args:
        words: The words the reader gave, for example a relative's office.
        label: What the words are, for the detail.
        text: The application's text.
        anchor: The application's anchor.

    Returns:
        A ``words-verbatim.v1`` result.
    """
    where = anchor.partition(":")[2]
    return _outcome(
        WORDS_CHECK,
        contains_word_for_word(words, text),
        passed=f"the {label} '{words}' is written in the application {where}",
        failed=f"the {label} '{words}' is not written in the application {where}",
    )


def read_date(text: str) -> str | None:
    """Read a date as an application writes it into ``YYYY-MM-DD``.

    Args:
        text: The date as written, such as ``11 September 1975``.

    Returns:
        The date, or None when no known way of writing a date reads it or it is not a real date.
    """
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), pattern).date().isoformat()
        except ValueError:
            continue
    return None


def check_date(quote: str, value: str, *, anchor: str) -> CheckResult:
    """Check that the date as written reads as the date the fact gives.

    Args:
        quote: The date as the application writes it.
        value: The date the reader gave, ``YYYY-MM-DD``.
        anchor: The application's anchor.

    Returns:
        A ``date-reads-as.v1`` result.
    """
    read = read_date(quote)
    return _outcome(
        DATE_CHECK,
        read is not None and read == value,
        passed=f"'{quote}' reads as {value}",
        failed=(
            f"'{quote}' reads as {read}, not {value}"
            if read is not None
            else f"'{quote}' is not a date this check can read, so {value} is not confirmed"
        ),
    )


def check_amount(amount: str, text: str | None, *, anchor: str) -> CheckResult:
    """Check that an amount is written in the application as the reader gave it.

    Args:
        amount: The amount the reader gave.
        text: The application's text.
        anchor: The application's anchor.

    Returns:
        An ``amount-verbatim.v1`` result.
    """
    where = anchor.partition(":")[2]
    return _outcome(
        AMOUNT_CHECK,
        contains_word_for_word(amount, text),
        passed=f"the amount '{amount}' is written in the application {where}",
        failed=f"the amount '{amount}' is not written in the application {where}",
    )


def check_score(applicant_name: str, entry_name: str, stated: str) -> CheckResult:
    """Check a screening's score against the starter's measure of the two names.

    Args:
        applicant_name: The applicant's name.
        entry_name: The list entry's name.
        stated: The score the screening states, to two places.

    Returns:
        A ``name-score.v1`` result.
    """
    computed = f"{round(name_similarity(applicant_name, entry_name), 2):.2f}"
    return _outcome(
        SCORE_CHECK,
        computed == stated,
        passed=f"'{applicant_name}' and '{entry_name}' score {computed}",
        failed=f"'{applicant_name}' and '{entry_name}' score {computed}, not '{stated}'",
    )


def check_dob_comparison(
    applicant_dob: str | None, entry_dob: str | None, stated: bool | None
) -> CheckResult:
    """Check a screening's comparison of dates of birth against the two dates.

    Args:
        applicant_dob: The applicant's date of birth, or None when it was not established.
        entry_dob: The list entry's, or None when the list gives none.
        stated: What the screening says: agree, differ, or None when it cannot be compared.

    Returns:
        A ``dob-comparison.v1`` result.
    """
    expected = None if applicant_dob is None or entry_dob is None else applicant_dob == entry_dob
    return _outcome(
        DOB_CHECK,
        expected == stated,
        passed=f"dates of birth {applicant_dob or 'not established'} and "
        f"{entry_dob or 'not given'}: {_words(expected)}",
        failed=f"the dates {applicant_dob or 'not established'} and {entry_dob or 'not given'} "
        f"give {_words(expected)}, not {_words(stated)}",
    )


def _words(value: bool | None) -> str:
    return "cannot be compared" if value is None else ("agree" if value else "differ")


def check_proposal(attributes: dict) -> CheckResult:
    """Check a proposal's risk level and decision against the rule and what the checks found.

    Args:
        attributes: The proposal fact's attributes.

    Returns:
        A ``proposal-follows-checks.v1`` result.
    """
    expected = decide(
        name_checked=bool(attributes["name_checked"]),
        sanctions_match=attributes["sanctions_match"],
        unsettled=attributes["unsettled"],
    )
    given = (attributes["settled"], attributes["risk_level"], attributes["decision"])
    return _outcome(
        PROPOSAL_CHECK,
        given == tuple(expected),
        passed=(
            f"the rule gives {expected.risk_level} risk and {expected.decision} for what was found"
        ),
        failed=(
            f"the rule gives {tuple(expected)} for what was found, and the proposal says {given}"
        ),
    )
