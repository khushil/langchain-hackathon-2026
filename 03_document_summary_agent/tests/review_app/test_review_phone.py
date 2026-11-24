"""Every page of the compliance brief at 390 by 844: nothing scrolls sideways, controls in reach."""

from __future__ import annotations

import pytest
from review_browser_support import Served
from test_review_browser import PAGES

from fsi_common.app.browser_checks import answer_problems, narrow_problems

PHONE = (390, 844)


@pytest.mark.parametrize("name", sorted(PAGES))
def test_each_page_fits_a_phone_window_with_sign_out_in_reach(browser, served: Served, name):
    path, _ = PAGES[name]
    context, page = served.open(browser, PHONE)
    page.goto(served.base_url + path)
    assert narrow_problems(page) == []
    assert answer_problems(page, tall_exhibit_allowed=True) == []
    box = page.locator("header button:has-text('Sign out')").bounding_box()
    assert box and box["x"] + box["width"] <= PHONE[0]
    context.close()


def test_the_review_page_with_a_source_open_fits_a_phone_window(browser, served: Served):
    review = served.runs._runs["run-1"].review
    fact = review.request.statements[2].facts[0].fact
    context, page = served.open(browser, PHONE)
    page.goto(served.base_url + PAGES["review"][0] + f"?fact={fact.id}")
    assert page.inner_text("[data-hook=paragraph] mark") == fact.quote
    assert narrow_problems(page) == []
    context.close()


def test_a_planted_wide_block_on_the_review_page_fails_the_phone_check(browser, served: Served):
    context, page = served.open(browser, PHONE)
    page.goto(served.base_url + PAGES["review"][0])
    page.evaluate(
        "() => { const e = document.createElement('div'); e.style.width = '1500px';"
        " e.textContent = 'wide'; document.querySelector('.exhibit').append(e); }"
    )
    assert narrow_problems(page) != []
    context.close()
