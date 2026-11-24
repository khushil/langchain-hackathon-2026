"""The plain-code checks on an obligation: its quote and its deadline are the paragraph's words."""

from __future__ import annotations

from context.text import contains_word_for_word
from fsi_common.records import CheckResult
from sub_agent import Obligation
from utils.records import paragraph_anchor

QUOTE_CHECK = "quote-verbatim.v1"
"""The check that a fact's quote is word for word in the paragraph it cites."""

DEADLINE_CHECK = "deadline-verbatim.v1"
"""The check that a fact's deadline is word for word in the paragraph it cites."""


def _check(name: str, text: str, paragraph_text: str | None, *, anchor: str) -> CheckResult:
    number = anchor.partition(":")[2]
    if paragraph_text is None:
        return CheckResult(
            check=name,
            outcome="fail",
            detail=f"there is no such paragraph as {number} to compare '{text}' with",
        )
    if contains_word_for_word(text, paragraph_text):
        return CheckResult(
            check=name, outcome="pass", detail=f"found word for word in paragraph {number}"
        )
    return CheckResult(
        check=name,
        outcome="fail",
        detail=f"'{text}' is not found word for word in paragraph {number}",
    )


def check_quote(quote: str, paragraph_text: str | None, *, anchor: str) -> CheckResult:
    """Check that a quote is word for word in the paragraph it cites.

    Args:
        quote: The quote the model gave.
        paragraph_text: The paragraph's text, or None when the paragraph was not found.
        anchor: The paragraph's anchor, for the detail.

    Returns:
        A ``quote-verbatim.v1`` result saying what was compared and what was found.
    """
    return _check(QUOTE_CHECK, quote, paragraph_text, anchor=anchor)


def check_deadline(deadline: str, paragraph_text: str | None, *, anchor: str) -> CheckResult:
    """Check that a deadline is written word for word in the paragraph it cites.

    Args:
        deadline: The deadline the model gave.
        paragraph_text: The paragraph's text, or None when the paragraph was not found.
        anchor: The paragraph's anchor, for the detail.

    Returns:
        A ``deadline-verbatim.v1`` result saying what was compared and what was found.
    """
    return _check(DEADLINE_CHECK, deadline, paragraph_text, anchor=anchor)


def checks_for(obligation: Obligation, paragraph_text: str | None) -> list[CheckResult]:
    """Run every check an obligation is due: the quote always, the deadline when it has one.

    Args:
        obligation: The obligation as the section sub-agent returned it.
        paragraph_text: The text of the paragraph it cites, or None when there is none.

    Returns:
        The results, quote first.
    """
    anchor = paragraph_anchor(obligation.paragraph)
    results = [check_quote(obligation.evidence, paragraph_text, anchor=anchor)]
    if obligation.deadline is not None:
        results.append(check_deadline(obligation.deadline, paragraph_text, anchor=anchor))
    return results
