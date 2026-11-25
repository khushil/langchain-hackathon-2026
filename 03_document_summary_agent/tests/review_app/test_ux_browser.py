"""The reviewer's pages on the whole seeded document, in a real browser at a laptop and a phone."""

from __future__ import annotations

from typing import Any

import pytest
from review_seeded_support import Seeded, make_seeded

from fsi_common.app.browser_checks import (
    answer_problems,
    clickable_problems,
    clipped_problems,
    contrast_problems,
    narrow_problems,
    type_floor_problems,
)
from review_app.context import PREFIX

LAPTOP = (1366, 768)
WIDE = (1920, 1080)
PHONE = (390, 844)

_MAP = """
() => {
  const map = document.querySelector('[data-hook="map"]');
  const cells = [...document.querySelectorAll('.map-cell')];
  const box = e => e.getBoundingClientRect();
  let scrolls = false;
  for (let e = map; e; e = e.parentElement) {
    const y = getComputedStyle(e).overflowY;
    if ((y === 'auto' || y === 'scroll') && e.scrollHeight > e.clientHeight + 1) scrolls = true;
  }
  return {
    cells: cells.length,
    titles: document.querySelectorAll('.map-title').length,
    sideways: cells.filter(c => box(c).right > innerWidth || box(c).left < 0)
      .map(c => c.dataset.para),
    below: cells.filter(c => box(c).bottom > innerHeight || box(c).top < 0)
      .map(c => c.dataset.para),
    scrolls,
    smallest: Math.min(...cells.map(c => parseFloat(getComputedStyle(c).fontSize))),
  };
}
"""

_FOLD = """
() => {
  const first = document.querySelector('[data-hook="statement"]');
  const link = first && first.querySelector('a.fact-link');
  const form = document.querySelector('[data-hook="decision-form"] button[type=submit]');
  const text = link ? link.innerText.toLowerCase() : '';
  const reason = document.querySelector('#reason');
  const at = e => (e ? e.getBoundingClientRect().bottom : null);
  return { statement: at(first), link: at(link), button: at(form), reason: at(reason),
           about_firm: text.includes('firm profile'),
           height: innerHeight, scrollable: document.documentElement.scrollHeight - innerHeight };
}
"""

_PROFILE = """
() => {
  const pane = document.querySelector('[data-hook="profile"]');
  const links = [...pane.querySelectorAll('a.fact-link')];
  const hit = links.filter(a => {
    a.scrollIntoView({block: 'center'});
    for (let e = a.parentElement; e; e = e.parentElement) e.scrollLeft = 0;
    const b = a.getBoundingClientRect();
    const at = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
    return !(at === a || a.contains(at)) || b.right > innerWidth || b.left < 0;
  }).length;
  const cut = [...pane.querySelectorAll('.badge')]
    .filter(b => b.scrollWidth > b.clientWidth + 1).length;
  return { links: links.length, unreachable: hit, cutBadges: cut,
           sideways: pane.scrollWidth - pane.clientWidth };
}
"""


@pytest.fixture(scope="module")
def served() -> Seeded:
    """The seeded application served for a browser; the tests here only read it."""
    found = make_seeded()
    found.serve()
    yield found
    found.stop()


@pytest.fixture(scope="module")
def carried() -> Seeded:
    """The seeded application with a second brief started, whose decisions are carried."""
    found = make_seeded()
    found.second = found.start_another()
    found.serve()
    yield found
    found.stop()


def go(served: Seeded, browser, size, path: str):
    """Open a page of the seeded brief that waits, at a size."""
    context, page = served.open(browser, size)
    page.goto(
        served.running.base_url + path.replace("{w}", served.waiting).replace("{s}", served.signed)
    )
    return context, page


def map_problems(page: Any, *, in_view: bool) -> list[str]:
    """Say what is wrong with the picture of the document: cut, scrolled or out of the window.

    Args:
        page: The page, loaded.
        in_view: Whether every box must be in the window without scrolling the page (a laptop);
            a phone only needs every box inside its width.
    """
    found = page.evaluate(_MAP)
    problems = []
    if found["cells"] != 48 or found["titles"] != 10:
        problems.append(f"The picture has {found['cells']} boxes in {found['titles']} sections.")
    if found["sideways"]:
        problems.append(f"Boxes beyond the window's width: {', '.join(found['sideways'])}.")
    if in_view and found["below"]:
        problems.append(f"Boxes below the fold: {', '.join(found['below'])}.")
    if found["scrolls"]:
        problems.append("The picture scrolls inside the page.")
    if found["smallest"] < 12:
        problems.append("A box is set below the 12 pixel floor.")
    return problems


def fold_problems(page: Any) -> list[str]:
    """Say whether the first obligation and the decision form are in view without scrolling."""
    found = page.evaluate(_FOLD)
    problems = []
    for name in ("statement", "link", "button", "reason"):
        if found[name] is None or found[name] > found["height"]:
            problems.append(f"The {name} is not above the fold.")
    if found["about_firm"]:
        problems.append(
            "The first statement is about the firm, not about what the document requires."
        )
    return problems


def profile_problems(page: Any) -> list[str]:
    """Say whether every Source link of the profile can be clicked and no badge is cut."""
    found = page.evaluate(_PROFILE)
    problems = []
    if found["links"] != 12:
        problems.append(f"The profile has {found['links']} Source links, not 12.")
    if found["unreachable"]:
        problems.append(f"{found['unreachable']} Source links cannot be clicked where they are.")
    if found["cutBadges"]:
        problems.append(f"{found['cutBadges']} badges are cut off.")
    if found["sideways"] > 1:
        problems.append("The profile scrolls sideways.")
    return problems


@pytest.mark.parametrize("size", [LAPTOP, WIDE, PHONE], ids=lambda s: f"{s[0]}x{s[1]}")
def test_the_picture_holds_all_48_paragraphs_in_view_without_an_inner_scroll(browser, served, size):
    context, page = go(served, browser, size, "/compliance-brief/runs/{w}/review")
    assert map_problems(page, in_view=size != PHONE) == []
    if size == PHONE:
        assert narrow_problems(page) == []
    context.close()


def test_a_picture_cut_to_a_window_is_caught(browser, served):
    context, page = go(served, browser, LAPTOP, "/compliance-brief/runs/{w}/review")
    page.add_style_tag(content="[data-hook=map] { max-height: 60px; overflow: auto; }")
    found = map_problems(page, in_view=True)
    assert any("scrolls" in p for p in found)
    context.close()


@pytest.mark.parametrize("size", [LAPTOP, WIDE], ids=lambda s: f"{s[0]}x{s[1]}")
def test_the_first_obligation_and_the_decision_form_are_in_view(browser, served, size):
    context, page = go(served, browser, size, "/compliance-brief/runs/{w}/review")
    assert fold_problems(page) == []
    assert answer_problems(page, tall_exhibit_allowed=False) == []
    context.close()


def test_an_answer_that_pushes_the_first_obligation_below_the_fold_is_caught(browser, served):
    context, page = go(served, browser, LAPTOP, "/compliance-brief/runs/{w}/review")
    page.add_style_tag(content=".statements { margin-top: 900px; }")
    assert any("above the fold" in p for p in fold_problems(page))
    context.close()


@pytest.mark.parametrize("size", [LAPTOP, PHONE], ids=lambda s: f"{s[0]}x{s[1]}")
def test_every_source_link_of_the_firm_profile_can_be_clicked_and_no_badge_is_cut(
    browser, served, size
):
    context, page = go(served, browser, size, "/compliance-brief/runs/{w}/review?tab=profile")
    assert profile_problems(page) == []
    if size == PHONE:
        assert narrow_problems(page) == []
    context.close()


def test_a_profile_wider_than_its_pane_is_caught(browser, served):
    context, page = go(served, browser, LAPTOP, "/compliance-brief/runs/{w}/review?tab=profile")
    page.add_style_tag(content=".profile-row { min-width: 1500px; }")
    assert profile_problems(page) != []
    context.close()


def test_the_name_in_the_top_bar_is_not_cut_at_a_laptop_width(browser, served):
    context, page = go(served, browser, LAPTOP, "/compliance-brief/runs/{w}/review")
    who = page.locator("[data-hook=signed-in]")
    assert who.inner_text() == "Dana Whitfield, Head of Compliance"
    assert who.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
    context.close()


def test_a_question_reads_in_one_column_on_a_phone(browser, served):
    context, page = go(served, browser, PHONE, "/compliance-brief/runs/{w}/review?tab=questions")
    labels = page.locator("dl.record dt")
    assert labels.count() >= 3
    first = labels.first.bounding_box()
    value = page.locator("dl.record dd").first.bounding_box()
    assert abs(first["x"] - value["x"]) < 2 and value["width"] > 250
    assert narrow_problems(page) == []
    context.close()


@pytest.mark.parametrize(
    "path", ["/compliance-brief/runs/{s}/signed", "/compliance-brief/runs/{s}/facts"]
)
def test_a_table_on_a_phone_shows_every_column_without_a_sideways_scroll(browser, served, path):
    context, page = go(served, browser, PHONE, path)
    assert narrow_problems(page) == []
    wrap = page.locator("[data-hook=table]").first
    assert wrap.evaluate("e => e.parentElement.scrollWidth <= e.parentElement.clientWidth + 1")
    labels = (
        page.locator("[data-hook=table] tbody tr")
        .first.locator("td")
        .evaluate_all("tds => tds.map(td => td.dataset.label)")
    )
    assert labels and all(labels)
    context.close()


ROUTES = (
    "/",
    "/about",
    "/signin",
    "/compliance-brief/",
    "/compliance-brief/runs/{w}/review",
    "/compliance-brief/runs/{w}/review?tab=profile",
    "/compliance-brief/runs/{w}/review?tab=questions",
    "/compliance-brief/runs/{w}/review?tab=signoff",
    "/compliance-brief/runs/{w}/review?para=1.1",
    "/compliance-brief/runs/{w}/facts",
    "/compliance-brief/runs/{s}/signed",
    "/compliance-brief/runs/{s}/signed?para=1.1",
    "/compliance-brief/runs/{s}/facts",
)


@pytest.mark.parametrize("path", ROUTES)
def test_no_page_logs_a_console_error_or_gets_a_404(browser, served, path):
    context, page = served.open(browser, LAPTOP)
    problems: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.on(
        "response", lambda r: problems.append(f"{r.status} {r.url}") if r.status >= 400 else None
    )
    page.goto(
        served.running.base_url + path.replace("{w}", served.waiting).replace("{s}", served.signed)
    )
    page.wait_for_load_state("networkidle")
    assert problems == []
    context.close()


def test_the_document_digest_is_short_with_the_whole_value_on_hover_and_on_enter(browser, served):
    context, page = go(served, browser, LAPTOP, "/compliance-brief/runs/{w}/review")
    summary = page.locator("[data-hook=source] summary.digest").first
    shown = summary.inner_text()
    full = summary.get_attribute("title")
    assert full.startswith("sha256:") and len(full) > len(shown) and shown.endswith("…")
    assert not page.locator("[data-hook=source] details.digest-details code").first.is_visible()
    summary.focus()
    page.keyboard.press("Enter")
    assert page.locator("[data-hook=source] details.digest-details code").first.inner_text() == full
    context.close()


def test_the_review_pages_pass_the_sweeps_on_the_whole_document(browser, served):
    for path in (
        "/compliance-brief/runs/{w}/review",
        "/compliance-brief/runs/{w}/review?tab=profile",
    ):
        context, page = go(served, browser, LAPTOP, path)
        assert type_floor_problems(page) == []
        assert contrast_problems(page) == []
        assert clipped_problems(page) == []
        assert clickable_problems(page) == []
        context.close()


def test_a_real_click_on_a_box_of_the_picture_opens_its_paragraph(browser, served):
    context, page = go(served, browser, LAPTOP, "/compliance-brief/runs/{w}/review")
    page.click("a.map-cell[data-para='9.1']")
    page.wait_for_load_state()
    assert "fact=" in page.url or "para=9.1" in page.url
    assert "Paragraph 9.1" in page.inner_text("[data-hook=source]")
    assert PREFIX in page.url
    context.close()


@pytest.mark.parametrize("path", ROUTES)
def test_every_page_names_an_icon_so_a_browser_does_not_ask_for_one_and_get_a_404(served, path):
    page = served.client().get(path.replace("{w}", served.waiting).replace("{s}", served.signed))
    assert page.status_code == 200
    assert '<link rel="icon"' in page.text


@pytest.mark.parametrize("size", [PHONE, LAPTOP], ids=lambda s: f"{s[0]}x{s[1]}")
def test_a_carried_badge_wraps_inside_the_window_and_is_not_cut(browser, carried, size):
    context, page = carried.open(browser, size)
    page.goto(f"{carried.running.base_url}/compliance-brief/runs/{carried.second}/review")
    badges = page.locator("[data-hook=statements] .badge[data-state=carried]")
    assert badges.count() >= 10
    found = badges.evaluate_all(
        """els => els.filter(b => b.getBoundingClientRect().right > innerWidth
            || b.scrollWidth > b.clientWidth + 1).map(b => b.innerText)"""
    )
    assert found == []
    assert narrow_problems(page) == [] if size == PHONE else True
    context.close()


def test_a_badge_that_cannot_wrap_is_caught(browser, carried):
    context, page = carried.open(browser, PHONE)
    page.goto(f"{carried.running.base_url}/compliance-brief/runs/{carried.second}/review")
    page.add_style_tag(content="[data-state=carried] { white-space: nowrap !important; }")
    found = page.locator("[data-hook=statements] .badge[data-state=carried]").evaluate_all(
        "els => els.filter(b => b.getBoundingClientRect().right > innerWidth).length"
    )
    assert found > 0
    context.close()
