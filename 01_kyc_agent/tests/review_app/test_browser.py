"""The pages in a real browser: a laptop window of 1366 by 768 and a phone window of 390 by 844."""

from __future__ import annotations

import pytest
from browser_support import BASE, SIZES, picture_problems, shot

from fsi_common.app.browser_checks import (
    answer_problems,
    clickable_problems,
    clipped_problems,
    contrast_problems,
    narrow_problems,
    type_floor_problems,
)
from fsi_common.records import SETTLED_STATES  # noqa: E402

PHONE = SIZES[1]


def pages(served):
    """Every page of the topic, with whether its detail may run below the fold."""
    waiting, signed = served.waiting, served.signed
    return {
        "start": (f"{BASE}/", True),
        "batch": (f"{BASE}/runs/{waiting}/review", True),
        "application": (f"{BASE}/runs/{waiting}/applications/CUST-018", False),
        "application-settled": (f"{BASE}/runs/{waiting}/applications/CUST-016", False),
        "screenings": (f"{BASE}/runs/{waiting}/screenings", True),
        "signoff": (f"{BASE}/runs/{waiting}/signoff", False),
        "signed": (f"{BASE}/runs/{signed}/signed", True),
        "signed-application": (f"{BASE}/runs/{signed}/applications/CUST-018", False),
        "reading": (f"{BASE}/runs/{served.running}", False),
        "stopped": (f"{BASE}/runs/{served.failed}", False),
        "notfound": (f"{BASE}/runs/none/review", False),
        "about": ("/about", False),
        "home": ("/", False),
    }


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize(
    "name",
    [
        "start", "batch", "application", "application-settled", "screenings", "signoff",
        "signed", "signed-application", "reading", "stopped", "notfound", "about", "home",
    ],
)  # fmt: skip
def test_each_page_holds_the_answer_in_view_and_passes_every_sweep(browser, served, name, size):
    path, tall = pages(served)[name]
    context, page = served.open(browser, size)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(served.base_url + path)
    shot(page, name, size)
    assert answer_problems(page, tall_exhibit_allowed=tall or size == PHONE) == []
    assert type_floor_problems(page) == []
    assert contrast_problems(page) == []
    assert clipped_problems(page) == []
    assert clickable_problems(page) == []
    if size == PHONE:
        assert narrow_problems(page) == []
    assert errors == []
    context.close()


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_the_picture_is_in_view_whole_with_all_twenty_five_applications(browser, served, size):
    context, page = served.open(browser, size)
    page.goto(served.base_url + pages(served)["batch"][0])
    assert picture_problems(page) == []
    context.close()


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_the_headline_numbers_equal_an_independent_count_of_the_records(browser, served, size):
    state = served.runs.result(served.waiting)
    proposals = [c[0] for c in state["facts"].values() if c[0]["kind"] == "proposal"]
    settled = sum(p["attributes"]["settled"] for p in proposals)
    context, page = served.open(browser, size)
    page.goto(served.base_url + pages(served)["batch"][0])
    sentence = page.inner_text("[data-hook=sentence]")
    assert f"{len(proposals)} applications were screened against 14 list entries" in sentence
    assert (
        f"{settled} settled by the checks and {len(proposals) - settled} for a person" in sentence
    )
    tiles = [t.inner_text().split("\n")[0] for t in page.locator("[data-hook=tile]").all()]
    assert tiles[0] == str(len(proposals))
    asked = served.runs.review_request(served.waiting).open_questions
    carried = sum(q.state in SETTLED_STATES for q in asked)
    assert tiles[2] == f"{carried} of {len(asked)}"
    context.close()


def test_the_whole_review_through_the_browser_with_the_keyboard_and_a_real_click(browser, served):
    context, page = served.open(browser, SIZES[0])
    page.goto(served.base_url + pages(served)["batch"][0])
    before = page.locator("[data-hook=tile]").nth(1).inner_text().split("\n")[0]
    page.click('a[data-hook=picture-cell][data-state=needs][href$="/applications/CUST-002"]')
    assert page.url.endswith("/applications/CUST-002")
    page.get_by_label("Accept", exact=True).check()
    page.fill("#reason", "Checked the application against the list.")
    page.get_by_role("button", name="Record my decision").click()
    page.wait_for_load_state()
    assert page.locator("[data-hook=form-problem]").count() == 0
    page.goto(served.base_url + pages(served)["batch"][0])
    after = page.locator("[data-hook=tile]").nth(1).inner_text().split("\n")[0]
    assert int(after.split(" of ")[0]) == int(before.split(" of ")[0]) + 1
    context.close()


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_the_two_readings_sit_side_by_side_on_a_wide_screen_and_stack_on_a_phone(
    browser, served, size
):
    context, page = served.open(browser, size)
    page.goto(served.base_url + pages(served)["application"][0])
    same = page.locator("[data-hook=reading-same]").bounding_box()
    other = page.locator("[data-hook=reading-different]").bounding_box()
    assert same and other
    if size[0] >= 1100:
        assert abs(same["y"] - other["y"]) < 2 and same["x"] < other["x"]
    else:
        assert other["y"] > same["y"]
    context.close()


# Each sweep must be able to fail: a fault planted into a loaded page turns it red.


def test_a_missing_answer_sentence_is_found(browser, served):
    context, page = served.open(browser, SIZES[0])
    page.goto(served.base_url + pages(served)["batch"][0])
    page.evaluate("document.querySelector('[data-hook=sentence]').remove()")
    assert any("no answer sentence" in p for p in answer_problems(page, tall_exhibit_allowed=True))
    context.close()


def test_a_fourth_tile_is_found(browser, served):
    context, page = served.open(browser, SIZES[0])
    page.goto(served.base_url + pages(served)["batch"][0])
    page.evaluate(
        "document.querySelector('.tiles').insertAdjacentHTML('beforeend',"
        "'<div class=tile data-hook=tile>4</div>')"
    )
    assert any("4 tiles" in p for p in answer_problems(page, tall_exhibit_allowed=True))
    context.close()


def test_a_picture_pushed_below_the_fold_or_cut_short_is_found(browser, served):
    context, page = served.open(browser, SIZES[0])
    page.goto(served.base_url + pages(served)["batch"][0])
    page.evaluate("document.querySelector('.matrix').style.marginTop = '400px'")
    assert "The picture does not fit above the fold." in picture_problems(page)
    page.evaluate("document.querySelector('[data-hook=picture-row]').remove()")
    assert any("holds 24 rows" in p for p in picture_problems(page))
    context.close()


def test_a_dead_link_and_an_unnamed_button_are_found(browser, served):
    context, page = served.open(browser, SIZES[0])
    page.goto(served.base_url + pages(served)["application"][0])
    page.evaluate(
        "document.querySelector('.proposal').insertAdjacentHTML('beforeend',"
        "'<a>dead</a><button type=button>Go</button>')"
    )
    problems = clickable_problems(page)
    assert any("link without an address" in p for p in problems)
    assert any("has no title" in p for p in problems)
    context.close()


def test_a_wide_element_on_a_phone_is_found(browser, served):
    context, page = served.open(browser, PHONE)
    page.goto(served.base_url + pages(served)["batch"][0])
    page.evaluate(
        "document.querySelector('main').insertAdjacentHTML('beforeend',"
        "'<div style=\"width:900px\">wide</div>')"
    )
    assert narrow_problems(page) != []
    context.close()


def test_a_small_type_is_found(browser, served):
    context, page = served.open(browser, SIZES[0])
    page.goto(served.base_url + pages(served)["batch"][0])
    page.evaluate("document.querySelector('.entry-name').style.fontSize = '9px'")
    assert type_floor_problems(page) != []
    context.close()
