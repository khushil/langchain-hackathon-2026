"""What the transaction page does with an empty reason in a browser at 1366 by 768, and what the
guide's step 8 and its failure row say about it."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from review_browser_support import SIZES, Served

GUIDE = (Path(__file__).resolve().parents[3] / "docs" / "user-guide.md").read_text("utf-8")
SENTENCE = "Write your reason in your own words."
PROMPT = "Please fill out this field."
LAPTOP = SIZES[0]


@pytest.fixture(scope="module")
def served():
    server = Served()
    yield server
    server.stop()


def open_review(browser, served):
    """Open the waiting review, with every request that is a POST noted."""
    context, page = served.open(browser, LAPTOP)
    sent: list[str] = []
    page.on("request", lambda r: sent.append(r.url) if r.method == "POST" else None)
    page.goto(served.base_url + served.pages()["review"])
    return context, page, sent


def record(page, reason: str) -> None:
    form = page.locator('[data-hook="decision-form"]').first
    form.get_by_label("Agree with the proposal", exact=True).check()
    form.locator("textarea[name=reason]").fill(reason)
    form.get_by_role("button", name="Record my decision").click()
    page.wait_for_timeout(600)


def test_an_empty_reason_is_stopped_by_the_browser_before_anything_is_sent(browser, served):
    context, page, sent = open_review(browser, served)
    before = page.url
    record(page, "")
    reason = page.locator('[data-hook="decision-form"] textarea[name=reason]').first
    assert sent == [] and page.url == before
    assert reason.evaluate("e => e.validity.valueMissing") is True
    assert reason.evaluate("e => e.validationMessage") == PROMPT
    assert SENTENCE not in page.inner_text("body")
    context.close()


def test_a_reason_of_only_spaces_is_sent_and_the_page_refuses_it_in_words(browser, served):
    context, page, sent = open_review(browser, served)
    record(page, "   ")
    assert len(sent) == 1 and sent[0].endswith("/decide")
    assert SENTENCE in page.inner_text('[data-hook="form-problem"]')
    context.close()


def guide_problems(text: str) -> list[str]:
    """Name what step 8 and the failure row say about an empty reason that the page does not."""
    found = []
    section = text[text.index("## Transaction monitoring") :]
    step = re.search(r"^8\. .*$", section, re.M)
    if step is None:
        return ["the transaction section has no step 8"]
    words = step.group(0)
    if PROMPT not in words or "only spaces" not in words or SENTENCE not in words:
        found.append(
            "step 8 does not say the browser stops an empty box and the page refuses spaces"
        )
    if 'with "Your reason" empty. It is refused' in words:
        found.append("step 8 says the page answers an empty box")
    row = next((line for line in text.splitlines() if line.startswith(f'| "{SENTENCE[:-1]}')), "")
    if "only spaces" not in row or PROMPT not in row:
        found.append(
            "the failure table's row does not say the sentence is for a box of only spaces"
        )
    return found


def test_the_guide_says_what_the_page_does():
    assert guide_problems(GUIDE) == []


def test_the_checker_finds_the_old_wording_and_a_planted_wrong_one():
    assert len(guide_problems(GUIDE.replace("only spaces", "no letters"))) >= 1
    start = GUIDE.index("## Transaction monitoring")
    stale = (
        GUIDE[:start]
        + "## Transaction monitoring\n8. Choose Agree and click Record with "
        + f'"Your reason" empty. It is refused with "{SENTENCE}"\n'
    )
    assert len(guide_problems(stale)) >= 2
