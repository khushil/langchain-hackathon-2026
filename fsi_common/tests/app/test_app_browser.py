"""The shell in a real browser: fit, type floor, contrast, keyboard, offline, and planted faults."""

from __future__ import annotations

import pytest
from app_browser_support import SIZES, open_page, shot  # noqa: F401
from app_toy_topic import make_toy_folder

from fsi_common.app import AppConfig, create_app
from fsi_common.app.browser_checks import (
    answer_problems,
    clickable_problems,
    clipped_problems,
    contrast_problems,
    contrast_ratio,
    type_floor_problems,
)
from fsi_common.app.testing import serve

ADVICE = "regulatory advice"
ADVICE_OPENING = "Outputs of this product are not legal"
ROUTES = ("/", "/about", "/signin", "/toy/", "/nowhere")


@pytest.fixture()
def server(tmp_path):
    folder = make_toy_folder(tmp_path)
    app = create_app(AppConfig(secret=b"browser-secret", topic_folders=(folder,)))
    running = serve(app)
    yield running
    running.stop()


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("route", ROUTES)
def test_each_shell_page_fits_and_passes_the_sweeps_at_both_sizes(browser, server, route, size):
    context, page = open_page(browser, server.base_url, size)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server.base_url + route)
    shot(page, "shell" + (route.strip("/").replace("/", "-") or "home"), size)
    assert answer_problems(page) == []
    assert type_floor_problems(page) == []
    assert contrast_problems(page) == []
    assert clipped_problems(page) == []
    assert clickable_problems(page) == []
    assert errors == []
    context.close()


def test_the_advice_sentence_is_on_the_about_page_alone(browser, server):
    context, page = open_page(browser, server.base_url, SIZES[0])
    holders = []
    for route in ROUTES:
        page.goto(server.base_url + route)
        if ADVICE in page.inner_text("body"):
            holders.append(route)
    assert holders == ["/about"]
    page.goto(server.base_url + "/about")
    assert ADVICE_OPENING in page.inner_text("body")
    context.close()


def test_nothing_is_fetched_from_outside_the_application_on_any_page(browser, server):
    context, page = open_page(browser, server.base_url, SIZES[0])
    outside = []
    context.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.url.startswith(server.base_url)
            else (outside.append(route.request.url), route.abort())
        ),
    )
    for route in ROUTES:
        page.goto(server.base_url + route)
    assert outside == []
    context.close()


def test_a_person_signs_in_and_out_with_the_keyboard_and_a_real_click(browser, server):
    context, page = open_page(browser, server.base_url, SIZES[0])
    page.goto(server.base_url + "/signin?next=/toy/")
    page.fill("#name", "Dana Whitfield")
    page.fill("#role", "Head of Compliance")
    page.keyboard.press("Enter")
    page.wait_for_url(server.base_url + "/toy/")
    assert "Dana Whitfield, Head of Compliance" in page.inner_text("header")
    page.click("text=Sign out")
    page.wait_for_url(server.base_url + "/")
    assert "Dana Whitfield" not in page.inner_text("header")
    context.close()


def test_a_machine_name_is_refused_on_the_page_in_words(browser, server):
    context, page = open_page(browser, server.base_url, SIZES[0])
    page.goto(server.base_url + "/signin")
    page.fill("#name", "Claude")
    page.fill("#role", "Head of Compliance")
    page.click("button[type=submit]")
    assert "a model, a program or a service" in page.inner_text("[data-hook=problem]")
    context.close()


def test_contrast_of_the_declared_colours_meets_the_rule():
    import re
    from pathlib import Path

    css = (Path(__file__).resolve().parents[2] / "fsi_common/app/static/app.css").read_text()
    tokens = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", css))

    def rgb(name):
        h = tokens[name].lstrip("#")
        return f"rgb({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)})"

    text_on_surface = [
        ("ink", "surface"),
        ("ink", "bg"),
        ("muted", "surface"),
        ("muted", "bg"),
        ("ink", "mark"),
        ("amber-ink", "amber-bg"),
        ("coral-ink", "coral-bg"),
        ("control-ink", "control"),
        ("ink", "amber-bg"),
        ("ink", "coral-bg"),
    ]
    for foreground, background in text_on_surface:
        assert contrast_ratio(rgb(foreground), rgb(background)) >= 4.5, (foreground, background)
    lines = [
        ("line", "surface"),
        ("line", "bg"),
        ("focus", "surface"),
        ("focus", "bg"),
        ("amber-line", "amber-bg"),
        ("coral-line", "coral-bg"),
    ]
    for line, surface in lines:
        assert contrast_ratio(rgb(line), rgb(surface)) >= 3.0, (line, surface)


@pytest.fixture()
def planted(browser, server):
    context, page = open_page(browser, server.base_url, SIZES[0])
    page.goto(server.base_url + "/toy/")
    yield page
    context.close()


PLANT = """([tag, text, attrs]) => {
  const el = document.createElement(tag);
  el.textContent = text;
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  document.querySelector('.exhibit').append(el);
  return el;
}"""


def plant(page, tag, text, **attrs):
    page.evaluate(PLANT, [tag, text, attrs])


def test_a_planted_bare_clickable_fails_the_clickable_sweep(planted):
    plant(planted, "div", "Go", onclick="void 0")
    assert any("neither a link nor a button" in p for p in clickable_problems(planted))


def test_a_planted_pointer_cursor_on_a_bare_div_fails_the_clickable_sweep(planted):
    plant(planted, "div", "Go", style="cursor:pointer")
    assert any("neither a link nor a button" in p for p in clickable_problems(planted))


def test_a_pointer_inherited_by_the_text_inside_a_link_passes_the_clickable_sweep(planted):
    assert clickable_problems(planted) == []
    planted.evaluate(
        "() => { const a = document.createElement('a'); a.href = '/about'; a.title = 'Open about';"
        " a.innerHTML = '<span>Inside the link</span>'; document.querySelector('main').append(a); }"
    )
    assert clickable_problems(planted) == []


def test_a_planted_listener_on_a_span_fails_the_clickable_sweep(planted):
    plant(planted, "span", "Open", id="listener")
    planted.evaluate(
        "() => document.getElementById('listener').addEventListener('click', () => {})"
    )
    assert any("neither a link nor a button" in p for p in clickable_problems(planted))


def test_a_planted_link_without_a_title_fails_the_clickable_sweep(planted):
    plant(planted, "a", "More", href="/about")
    assert any("no title naming its action" in p for p in clickable_problems(planted))


def test_a_planted_default_cursor_fails_the_clickable_sweep(planted):
    planted.add_style_tag(content="a[href='/about'] { cursor: default; }")
    assert any("pointer cursor" in p for p in clickable_problems(planted))


def test_a_planted_missing_focus_ring_fails_the_clickable_sweep(planted):
    planted.add_style_tag(content=":focus-visible { outline: none !important; }")
    assert any("focus ring" in p for p in clickable_problems(planted))


def test_a_planted_tiny_text_fails_the_type_floor(planted):
    planted.add_style_tag(content=".exhibit p { font-size: 10px; }")
    assert any("is 10 pixels" in p for p in type_floor_problems(planted))


def test_a_planted_pale_text_fails_the_contrast_sweep(planted):
    planted.add_style_tag(content=".exhibit p { color: #aab2bd; }")
    assert any("to 1" in p for p in contrast_problems(planted))


def test_a_planted_cut_off_name_without_a_title_fails_the_clipped_sweep(planted):
    plant(
        planted,
        "span",
        "A very long name " * 8,
        style="display:block;width:60px;overflow:hidden;white-space:nowrap",
    )
    assert any("is cut off" in p for p in clipped_problems(planted))


def test_a_planted_fourth_tile_and_a_second_exhibit_fail_the_answer_check(planted):
    add = (
        "([hook]) => { const e = document.createElement('div'); e.setAttribute('data-hook', hook); "
    )
    add += "e.textContent = 'x'; "
    add += "(hook === 'tile' ? document.querySelector('.tiles') : document.body).append(e); }"
    for hook in ("tile", "tile", "tile", "exhibit"):
        planted.evaluate(add, [hook])
    problems = answer_problems(planted)
    assert any("tiles" in p for p in problems) and any("2 exhibits" in p for p in problems)


def test_a_planted_overflow_fails_the_answer_check(planted):
    planted.add_style_tag(content=".exhibit { height: 2000px; }")
    assert any("scrolls by" in p for p in answer_problems(planted))
    planted.evaluate("() => { document.querySelector('.answer').style.height = '10px'; }")
    assert any("answer region has a scrollbar" in p for p in answer_problems(planted))
