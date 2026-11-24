"""A refused decision is said in words beside the fact the reviewer was deciding on."""

from __future__ import annotations

import re

import pytest
from review_fixtures import make_client
from review_helpers import RUN, decide, text_of

from fsi_common.examples.data import build_examples

AMEND_WORDS = "Write the amended wording in your own words."


def _problem_in_the_panel(html: str) -> str:
    """Return the text of the form problem that sits inside the source panel, or an empty string."""
    panel = re.search(r'<aside class="pane source".*?</aside>', html, flags=re.S)
    assert panel, "the page has no source panel"
    found = re.search(r'data-hook="form-problem".*?</p>', panel.group(0), flags=re.S)
    return text_of(found.group(0)) if found else ""


def test_an_amend_without_wording_on_a_fact_that_is_not_the_first_waiting_is_said_in_words(runs):
    ex = build_examples()
    review = runs._runs["run-1"].review
    assert review.request.statements[0].facts[0].fact.id == ex.fact_7_1.id  # still waiting
    refused = decide(
        make_client(runs),
        review,
        ex.fact_9_3,
        outcome="amend",
        amendment="",
        reason="The cause needs the firm's wording.",
    )
    assert refused.status_code == 422
    assert AMEND_WORDS in _problem_in_the_panel(refused.text)
    assert "Paragraph 9.3" in text_of(refused.text)  # the panel shows the fact that was decided on
    assert re.search(r'name="outcome" value="amend" checked', refused.text)
    assert "The cause needs the firm&#39;s wording." in refused.text  # the reason is kept


def test_the_amended_wording_box_is_marked_required_after_an_amend_was_refused(runs):
    ex = build_examples()
    review = runs._runs["run-1"].review
    refused = decide(make_client(runs), review, ex.fact_9_3, outcome="amend", amendment="")
    box = re.search(r'<textarea id="amendment"[^>]*>', refused.text)
    assert box and 'aria-required="true"' in box.group(0)
    fresh = make_client(runs).get(f"{RUN}/review", params={"fact": ex.fact_9_3.id})
    box = re.search(r'<textarea id="amendment"[^>]*>', fresh.text)
    assert box and "required" not in box.group(0)  # nothing is demanded before Amend is chosen


@pytest.mark.parametrize("outcome", ["accept", "reject"])
def test_a_missing_reason_on_a_fact_that_is_not_the_first_waiting_is_said_beside_that_fact(
    runs, outcome
):
    ex = build_examples()
    review = runs._runs["run-1"].review
    refused = decide(make_client(runs), review, ex.fact_9_3, outcome=outcome, reason="")
    assert refused.status_code == 422
    assert "Write your reason in your own words." in _problem_in_the_panel(refused.text)
