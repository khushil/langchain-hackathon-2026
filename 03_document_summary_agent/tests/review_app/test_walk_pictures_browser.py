"""The picture of the document and the firm profile in a real browser, at three window sizes."""

from __future__ import annotations

import re

import pytest
from review_browser_support import Served
from review_fakes import FakeRuns
from review_map_fakes import map_review
from review_table_fakes import tables_review

from fsi_common.app.browser_checks import (
    answer_problems,
    clickable_problems,
    clipped_problems,
    contrast_problems,
    narrow_problems,
    type_floor_problems,
)

BASE = "/compliance-brief/runs"
SIZES = ((1366, 768), (1920, 1080))
PAGES = {
    "map-review": (f"{BASE}/run-1/review", False),
    "map-facts": (f"{BASE}/run-1/facts", True),
    "profile": (f"{BASE}/run-2/review?tab=profile", False),
    "profile-facts": (f"{BASE}/run-2/facts", True),
}


@pytest.fixture()
def pictured():
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=map_review())
    runs.add("run-2", "awaiting_review", review=tables_review())
    server = Served(runs)
    yield server
    server.stop()


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("name", sorted(PAGES))
def test_each_page_holds_the_answer_in_view_and_passes_every_sweep(browser, pictured, name, size):
    path, tall = PAGES[name]
    context, page = pictured.open(browser, size)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(pictured.base_url + path)
    assert answer_problems(page, tall_exhibit_allowed=tall) == []
    assert type_floor_problems(page) == []
    assert contrast_problems(page) == []
    assert clipped_problems(page) == []
    assert clickable_problems(page) == []
    assert errors == []
    context.close()


@pytest.mark.parametrize("name", sorted(PAGES))
def test_each_page_fits_a_phone_window(browser, pictured, name):
    context, page = pictured.open(browser, (390, 844))
    page.goto(pictured.base_url + PAGES[name][0])
    assert narrow_problems(page) == []
    context.close()


def test_the_picture_and_the_answer_fit_together_at_1366_by_768(browser, pictured):
    context, page = pictured.open(browser, SIZES[0])
    page.goto(pictured.base_url + PAGES["map-review"][0])
    assert page.locator("[data-hook=map]").is_visible()
    box = page.locator("[data-hook=map]").bounding_box()
    assert box["y"] + min(box["height"], 160) <= 768
    pane = page.locator("aside.source").bounding_box()
    for selector in ("#reason", "text=Record my decision"):
        field = page.locator(selector).bounding_box()
        assert field["y"] + field["height"] <= pane["y"] + pane["height"], selector
    context.close()


def test_a_real_click_on_a_paragraph_opens_its_source_and_the_address_follows(browser, pictured):
    context, page = pictured.open(browser, SIZES[0])
    page.goto(pictured.base_url + PAGES["map-review"][0])
    page.click("[data-para='7.3']")
    page.wait_for_url(re.compile(r"fact="))
    assert "Paragraph 7.3" in page.inner_text("[data-hook=source]")
    assert page.get_attribute("[data-para='7.3']", "aria-current") == "true"
    page.click("[data-para='6.1']")
    page.wait_for_url(re.compile(r"para=6.1"))
    assert "Paragraph 6.1" in page.inner_text("[data-hook=source]")
    assert page.locator("[data-hook=decision-form]").count() == 0
    context.close()


def test_a_paragraph_is_reached_and_opened_from_the_keyboard(browser, pictured):
    context, page = pictured.open(browser, SIZES[0])
    page.goto(pictured.base_url + PAGES["map-review"][0])
    page.focus("[data-para='7.4']")
    page.keyboard.press("Enter")
    page.wait_for_url(re.compile(r"fact="))
    assert "Paragraph 7.4" in page.inner_text("[data-hook=source]")
    context.close()


def test_the_profile_is_confirmed_once_in_the_browser(browser, pictured):
    context, page = pictured.open(browser, SIZES[0])
    page.goto(pictured.base_url + PAGES["profile"][0])
    page.click("label:has-text('Accept')")
    page.fill("#profile-reason", "The tables say this.")
    page.click("text=Record my decision about the profile")
    page.wait_for_load_state()
    page.goto(pictured.base_url + PAGES["profile"][0])
    assert "covering 5 facts" in page.inner_text("[data-hook=profile-decision]")
    context.close()


def test_the_amended_profile_box_shows_once_amend_is_chosen(browser, pictured):
    context, page = pictured.open(browser, SIZES[0])
    page.goto(pictured.base_url + PAGES["profile"][0])
    assert not page.locator("#profile-amendment").is_visible()
    page.click("label:has-text('Amend')")
    assert page.locator("#profile-amendment").is_visible()
    context.close()
