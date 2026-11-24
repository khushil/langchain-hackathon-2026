"""The shell's pages at a phone width: no sideways scroll, every control in reach, tiles tidy."""

from __future__ import annotations

import pytest
from app_browser_support import open_page
from app_toy_topic import make_toy_folder

from fsi_common.app import AppConfig, create_app
from fsi_common.app.browser_checks import answer_problems, narrow_problems
from fsi_common.app.session import SessionCodec
from fsi_common.app.testing import serve
from fsi_common.records import Person

PHONE = (390, 844)
SECRET = b"phone-secret"
ROUTES = ("/", "/about", "/signin", "/toy/", "/nowhere")
LONG_ROLE = Person(name="Dana Whitfield", role="Head of Compliance")


@pytest.fixture()
def phone(browser, tmp_path):
    """A page at 390 by 844 on the toy application, signed in so that Sign out shows."""
    app = create_app(AppConfig(secret=SECRET, topic_folders=(make_toy_folder(tmp_path),)))
    running = serve(app)
    cookie = {
        "name": app.state.cookie_name,
        "value": SessionCodec(SECRET).encode(LONG_ROLE),
    }
    context, page = open_page(browser, running.base_url, PHONE, cookies=[cookie])
    yield running, page
    context.close()
    running.stop()


@pytest.mark.parametrize("route", ROUTES)
def test_each_shell_page_fits_a_phone_and_sign_out_is_in_reach(phone, route):
    running, page = phone
    page.goto(running.base_url + route)
    assert narrow_problems(page) == []
    assert answer_problems(page, tall_exhibit_allowed=True) == []
    box = page.locator("header button:has-text('Sign out')").bounding_box()
    assert box and box["x"] + box["width"] <= PHONE[0]


def test_a_planted_wide_element_fails_the_phone_check(phone):
    running, page = phone
    page.goto(running.base_url + "/toy/")
    page.evaluate(
        "() => { const e = document.createElement('div'); e.style.width = '1200px';"
        " e.textContent = 'wide'; document.querySelector('.exhibit').append(e); }"
    )
    problems = narrow_problems(page)
    assert any("wider than the 390 pixel window" in p for p in problems)
    assert any("beyond the right edge" in p for p in problems)


def test_a_planted_top_bar_that_does_not_wrap_fails_the_phone_check(phone):
    running, page = phone
    page.goto(running.base_url + "/toy/")
    page.add_style_tag(
        content=".topbar { flex-wrap: nowrap !important; } .topbar * { flex: none; }"
    )
    assert any("lies beyond the right edge" in p for p in narrow_problems(page))


def test_a_planted_tile_label_that_overflows_its_tile_fails_the_phone_check(phone):
    running, page = phone
    page.goto(running.base_url + "/toy/")
    page.add_style_tag(content=".tile-label { white-space: nowrap; overflow-wrap: normal; }")
    page.evaluate(
        "() => { document.querySelector('.tile-label').textContent = 'Assumptions accepted by the"
        " reviewer in their own words'; }"
    )
    assert any("spills out of its tile" in p for p in narrow_problems(page))


def test_a_table_that_scrolls_inside_its_own_frame_does_not_count_as_sideways(phone):
    running, page = phone
    page.goto(running.base_url + "/toy/")
    page.evaluate(
        "() => { const f = document.createElement('div'); f.className = 'table-wrap';"
        " const e = document.createElement('div'); e.style.width = '1200px'; e.textContent = 'row';"
        " f.append(e); document.querySelector('.exhibit').append(f); }"
    )
    assert narrow_problems(page) == []
