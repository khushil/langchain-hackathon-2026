"""The policy pages' tiles and picture in a real browser: whole words, room for the document
names, the first rows in view at 1366 by 768, and a picture that fits a phone."""

from __future__ import annotations

import pytest
from policy_pages_support import BASE, write_fake
from review_browser_support import Served
from review_fakes import FakeRuns

from fsi_common.app.browser_checks import narrow_problems

LAPTOP, WIDE, TABLET, PHONE = (1366, 768), (1920, 1080), (800, 900), (390, 844)
SIZES = (LAPTOP, WIDE, TABLET, PHONE)
ROWS_IN_VIEW = 3

# Every word of the text inside each match, with the lines its rectangles lie on. A word whose
# rectangles lie on two lines was broken inside; a vertical heading is read by its columns.
SPLIT_WORDS = """
(selector) => {
  const broken = [];
  for (const el of document.querySelectorAll(selector)) {
    const vertical = getComputedStyle(el).writingMode.startsWith('vertical');
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      for (const found of node.data.matchAll(/\\S+/g)) {
        const range = document.createRange();
        range.setStart(node, found.index);
        range.setEnd(node, found.index + found[0].length);
        const spots = [...range.getClientRects()].map(r => vertical ? r.left : r.top);
        if (spots.length > 1 && Math.max(...spots) - Math.min(...spots) > 3) broken.push(found[0]);
      }
    }
  }
  return broken;
}
"""
FIRST_ROWS = """
() => [...document.querySelectorAll('table.policy-grid')][0]
  ? [...document.querySelector('table.policy-grid').querySelectorAll('tr[data-obligation]')]
      .map(r => r.getBoundingClientRect().bottom)
  : []
"""
WIDTHS = """
() => ({
  page: document.documentElement.scrollWidth,
  window: window.innerWidth,
  frames: [...document.querySelectorAll('.policy-picture .table-wrap')]
    .map(f => [f.scrollWidth, f.clientWidth]),
})
"""


@pytest.fixture()
def served(tmp_path, monkeypatch):
    _, root = write_fake(tmp_path)
    monkeypatch.setenv("POLICY_BUNDLES_DIR", str(root))
    server = Served(FakeRuns())
    yield server
    server.stop()


def assessment_address(page, served) -> str:
    """The address of the first obligation that has an assessment, from the picture's button."""
    page.goto(served.base_url + BASE)
    return page.evaluate("document.querySelector('[data-hook=first-open-gap]').href")


def ids(size: tuple[int, int]) -> str:
    return f"{size[0]}x{size[1]}"


@pytest.mark.parametrize("size", SIZES, ids=ids)
@pytest.mark.parametrize("where", ("picture", "measures", "assessment"))
def test_no_word_of_a_tile_label_is_broken_across_lines(browser, served, where, size):
    context, page = served.open(browser, size)
    address = {
        "picture": served.base_url + BASE,
        "measures": served.base_url + BASE + "/measures",
    }.get(where) or assessment_address(page, served)
    page.goto(address)
    assert page.locator(".tile-label").count() >= 2
    assert page.evaluate(SPLIT_WORDS, ".tile-label") == []
    context.close()


@pytest.mark.parametrize("size", SIZES, ids=ids)
def test_every_document_name_in_the_picture_reads_whole(browser, served, size):
    context, page = served.open(browser, size)
    page.goto(served.base_url + BASE)
    assert page.locator("th.doc-head").count() == 18
    assert page.evaluate(SPLIT_WORDS, "th.doc-head") == []
    context.close()


def test_the_document_columns_have_room_and_the_first_rows_are_in_view(browser, served):
    context, page = served.open(browser, LAPTOP)
    page.goto(served.base_url + BASE)
    bottoms = page.evaluate(FIRST_ROWS)
    assert len(bottoms) >= ROWS_IN_VIEW
    assert max(bottoms[:ROWS_IN_VIEW]) <= LAPTOP[1], (
        f"row {ROWS_IN_VIEW} ends at {max(bottoms[:ROWS_IN_VIEW])}, below the window"
    )
    widths = page.evaluate(
        "() => [...document.querySelector('table.policy-grid').querySelectorAll('thead th')]"
        ".map(th => th.getBoundingClientRect().width)"
    )
    obligation, found, *documents = widths
    assert min(documents) >= 100, f"a document column is {min(documents):.0f} pixels wide"
    assert obligation + found <= 0.4 * sum(widths), "Obligation and Found take most of the width"
    context.close()


def test_the_picture_fits_a_phone_window(browser, served):
    context, page = served.open(browser, PHONE)
    page.goto(served.base_url + BASE)
    found = page.evaluate(WIDTHS)
    assert found["page"] <= found["window"], f"the page is {found['page']} pixels wide"
    assert all(scroll <= client + 1 for scroll, client in found["frames"]), found["frames"]
    assert narrow_problems(page) == []
    context.close()


def test_the_measures_fit_a_phone_window(browser, served):
    context, page = served.open(browser, PHONE)
    page.goto(served.base_url + BASE + "/measures")
    assert narrow_problems(page) == []
    context.close()


def test_the_checker_finds_a_planted_broken_word(browser, served):
    context, page = served.open(browser, PHONE)
    page.goto(served.base_url + BASE)
    page.evaluate(
        "() => { const el = document.querySelector('.tile-label');"
        " el.style.width = '3ch'; el.style.overflowWrap = 'anywhere'; }"
    )
    assert page.evaluate(SPLIT_WORDS, ".tile-label") != []
    context.close()
