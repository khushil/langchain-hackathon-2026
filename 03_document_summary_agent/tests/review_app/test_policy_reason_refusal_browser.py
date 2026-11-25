"""What the policy assessment page does with an empty reason in a browser at 1366 by 768, and
what the guide's step 4 and its failure row say about it."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from policy_pages_support import BASE, write_fake
from review_browser_support import Served
from review_fakes import FakeRuns

GUIDE = (Path(__file__).resolve().parents[3] / "docs" / "user-guide.md").read_text("utf-8")
SECTION = GUIDE[GUIDE.index("## Policy assessment") : GUIDE.index("## KYC onboarding")]
SENTENCE = "Write your reason in your own words."
PROMPT = "Please fill out this field."
LAPTOP = (1366, 768)


@pytest.fixture()
def served(tmp_path, monkeypatch):
    _, root = write_fake(tmp_path)
    monkeypatch.setenv("POLICY_BUNDLES_DIR", str(root))
    server = Served(FakeRuns())
    yield server
    server.stop()


def open_assessment(browser, served):
    """Open the first assessment that needs a decision, with every request that is a POST noted."""
    context, page = served.open(browser, LAPTOP)
    sent: list[str] = []
    page.on("request", lambda r: sent.append(r.url) if r.method == "POST" else None)
    page.goto(served.base_url + BASE)
    page.goto(page.evaluate("document.querySelector('[data-hook=first-open-gap]').href"))
    return context, page, sent


def record(page, reason: str) -> None:
    form = page.locator('[data-hook="decision-form"]')
    form.get_by_label("Accept", exact=True).check()
    form.locator("textarea[name=reason]").fill(reason)
    form.get_by_role("button", name="Record my decision").click()
    page.wait_for_timeout(600)


def test_an_empty_reason_is_stopped_by_the_browser_before_anything_is_sent(browser, served):
    context, page, sent = open_assessment(browser, served)
    before = page.url
    record(page, "")
    reason = page.locator('[data-hook="decision-form"] textarea[name=reason]')
    assert sent == [] and page.url == before
    assert reason.evaluate("e => e.validity.valueMissing") is True
    assert reason.evaluate("e => e.validationMessage") == PROMPT
    assert SENTENCE not in page.inner_text("body")
    context.close()


def test_a_reason_of_only_spaces_is_sent_and_the_page_refuses_it_in_words(browser, served):
    context, page, sent = open_assessment(browser, served)
    record(page, "   ")
    assert len(sent) == 1
    assert SENTENCE in page.inner_text('[data-hook="form-problem"]')
    context.close()


def guide_problems(text: str) -> list[str]:
    """Name what step 4 and the failure row say about an empty reason that the page does not."""
    found = []
    section = text[text.index("## Policy assessment") : text.index("## KYC onboarding")]
    step = re.search(r"^4\. .*$", section, re.M)
    if step is None:
        return ["the policy section has no step 4"]
    words = step.group(0)
    if PROMPT not in words or "only spaces" not in words or SENTENCE not in words:
        found.append(
            "step 4 does not say the browser stops an empty box and the page refuses spaces"
        )
    if "Without your reason nothing is recorded, and the page says" in words:
        found.append("step 4 says the page answers an empty box")
    row = next((line for line in text.splitlines() if line.startswith(f'| "{SENTENCE[:-1]}')), "")
    if "only spaces" not in row or PROMPT not in row:
        found.append(
            "the failure table's row does not say the sentence is for a box of only spaces"
        )
    return found


def test_the_guide_says_what_the_page_does():
    assert guide_problems(GUIDE) == []


def test_the_checker_finds_the_old_wording_and_a_planted_wrong_one():
    planted = GUIDE.replace("only spaces", "no letters")
    assert len(guide_problems(planted)) >= 1
    old_step = (
        f'4. Choose Accept. Without your reason nothing is recorded, and the page says "{SENTENCE}"'
    )
    start = GUIDE.index("## Policy assessment")
    stale = GUIDE[:start] + "## Policy assessment\n" + old_step + "\n## KYC onboarding\n"
    assert len(guide_problems(stale)) >= 2
