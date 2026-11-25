"""Every page of the topic in a real browser at a laptop and a phone, with planted faults."""

from __future__ import annotations

import pytest
from review_browser_support import SIZES, Served, shot

from fsi_common.app.browser_checks import (
    answer_problems,
    clickable_problems,
    clipped_problems,
    contrast_problems,
    narrow_problems,
    type_floor_problems,
)

LAPTOP, PHONE = SIZES


@pytest.fixture(scope="module")
def served():
    server = Served()
    yield server
    server.stop()


PAGE_NAMES = (
    "start",
    "running",
    "failed",
    "review",
    "review-open",
    "questions",
    "history",
    "signoff",
    "signed",
)


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("name", PAGE_NAMES)
def test_each_page_opens_on_its_answer_and_passes_the_sweeps_at_both_sizes(
    browser, served, name, size
):
    path = served.pages()[name]
    context, page = served.open(browser, size)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(served.base_url + path)
    shot(page, name, size)
    assert answer_problems(page, tall_exhibit_allowed=True) == []
    assert type_floor_problems(page) == []
    assert contrast_problems(page) == []
    assert clipped_problems(page) == []
    assert clickable_problems(page) == []
    if size == PHONE:
        assert narrow_problems(page) == []
    assert errors == []
    context.close()


def test_the_answer_of_the_review_fits_above_the_fold_at_a_laptop(browser, served):
    context, page = served.open(browser, LAPTOP)
    page.goto(served.base_url + served.pages()["review"])
    box = page.locator('[data-hook="answer"]').bounding_box()
    assert box["y"] + box["height"] <= LAPTOP[1]
    assert page.locator('[data-hook="tile"]').count() == 3
    assert page.locator('[data-hook="exhibit"]').count() == 1
    context.close()


def test_the_picture_draws_each_transaction_once_and_the_headline_equals_its_count(browser, served):
    context, page = served.open(browser, LAPTOP)
    page.goto(served.base_url + served.pages()["review"])
    marks = page.locator('[data-hook="mark"]')
    assert marks.count() == 10
    assert page.inner_text('[data-hook="stream-count"]') == "10 of 10 transactions marked"
    tiles = page.locator('[data-hook="tile"] .tile-value').all_inner_texts()
    assert tiles[0] == "10" and tiles[1] == "6 of 10"
    context.close()


def test_a_real_click_on_a_mark_opens_its_transaction_and_a_reload_keeps_it(browser, served):
    context, page = served.open(browser, LAPTOP)
    page.goto(served.base_url + served.pages()["review"])
    page.click('svg a[data-tx="TX-1008"]')
    page.wait_for_url("**tx=TX-1008")
    assert "TX-1008, StreamFlix" in page.inner_text('[data-hook="transaction-title"]')
    page.reload()
    assert "TX-1008, StreamFlix" in page.inner_text('[data-hook="transaction-title"]')
    assert page.locator('svg a[data-tx="TX-1008"]').get_attribute("aria-current") == "true"
    context.close()


def test_a_real_click_on_a_statements_link_opens_the_same_transaction(browser, served):
    context, page = served.open(browser, LAPTOP)
    page.goto(served.base_url + served.pages()["review"])
    page.click('a.fact-link:has-text("TX-1004")')
    page.wait_for_url("**tx=TX-1004")
    assert "TX-1004, Taberna do Largo" in page.inner_text('[data-hook="transaction-title"]')
    context.close()


def test_choosing_to_give_ones_own_decision_shows_its_fields_and_agreeing_hides_them(
    browser, served
):
    context, page = served.open(browser, LAPTOP)
    page.goto(served.base_url + served.pages()["review-open"])
    assert not page.locator(".amend-field").is_visible()
    page.check('input[name="outcome"][value="amend"]')
    assert page.locator(".amend-field").is_visible()
    page.check('input[name="outcome"][value="accept"]')
    assert not page.locator(".amend-field").is_visible()
    context.close()


def test_the_decision_form_is_reached_and_used_from_the_keyboard(browser, served):
    context, page = served.open(browser, LAPTOP)
    page.goto(served.base_url + served.pages()["review-open"])
    page.focus('input[name="outcome"][value="accept"]')
    page.keyboard.press("Space")
    assert page.is_checked('input[name="outcome"][value="accept"]')
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.name") == "reason"
    page.keyboard.type("Checked.")
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.tagName") == "BUTTON"
    context.close()


def test_a_finished_brief_shows_no_alert_colour_anywhere(browser, served):
    context, page = served.open(browser, LAPTOP)
    page.goto(served.base_url + served.pages()["signed"])
    assert (
        page.locator(".badge-needs, .badge-failed, .tile-needs_person, .tile-failed").count() == 0
    )
    states = page.locator('[data-hook="mark"]').evaluate_all("els => els.map(e => e.dataset.state)")
    assert set(states) == {"decided"}
    context.close()


def test_nothing_is_fetched_from_outside_the_application_on_any_page(browser, served):
    context, page = served.open(browser, LAPTOP)
    outside = []
    context.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.url.startswith(served.base_url)
            else (outside.append(route.request.url), route.abort())
        ),
    )
    for name in PAGE_NAMES:
        page.goto(served.base_url + served.pages()[name])
    assert outside == []
    context.close()


def test_the_advice_sentence_is_on_the_about_page_alone(browser, served):
    context, page = served.open(browser, LAPTOP)
    holders = []
    for name in PAGE_NAMES:
        page.goto(served.base_url + served.pages()[name])
        if "regulatory advice" in page.inner_text("body"):
            holders.append(name)
    assert holders == []
    page.goto(served.base_url + "/about")
    assert "not legal, compliance or regulatory advice" in page.inner_text("body")
    context.close()


# Planted faults: each check must fail on the page it is meant to guard.


def planted(page, script: str) -> None:
    page.evaluate(script)


@pytest.mark.parametrize(
    ("name", "script", "check"),
    [
        (
            "review",
            "() => { const d = document.createElement('div'); d.textContent = 'x';"
            " d.addEventListener('click', () => {}); d.style.cursor = 'pointer';"
            " document.querySelector('.exhibit').append(d); }",
            clickable_problems,
        ),
        (
            "review",
            "() => { const d = document.createElement('p'); d.textContent = 'tiny';"
            " d.style.fontSize = '9px'; document.querySelector('.exhibit').append(d); }",
            type_floor_problems,
        ),
        (
            "review",
            "() => { const d = document.createElement('p'); d.textContent = 'pale';"
            " d.style.color = '#cccccc'; document.querySelector('.exhibit').append(d); }",
            contrast_problems,
        ),
        (
            "review",
            "() => { const d = document.createElement('div'); d.textContent = 'cut off text here';"
            " d.style.cssText = 'width:20px;overflow:hidden;white-space:nowrap';"
            " document.querySelector('.exhibit').append(d); }",
            clipped_problems,
        ),
        (
            "review",
            "() => { const t = document.createElement('div'); t.dataset.hook = 'tile';"
            " document.querySelector('.tiles').append(t, t.cloneNode(), t.cloneNode()); }",
            answer_problems,
        ),
    ],
)
def test_a_planted_fault_on_the_review_page_fails_its_sweep(browser, served, name, script, check):
    context, page = served.open(browser, LAPTOP)
    page.goto(served.base_url + served.pages()[name])
    page.evaluate(script)
    assert check(page) != []
    context.close()


def test_a_planted_wide_block_fails_the_phone_check(browser, served):
    context, page = served.open(browser, PHONE)
    page.goto(served.base_url + served.pages()["review"])
    page.evaluate(
        "() => { const e = document.createElement('div'); e.style.width = '1500px';"
        " e.textContent = 'wide'; document.querySelector('.exhibit').append(e); }"
    )
    assert narrow_problems(page) != []
    context.close()
