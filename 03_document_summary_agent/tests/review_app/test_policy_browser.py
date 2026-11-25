"""The policy pages in a real browser: the picture's column headings can be read at 1366 by 768."""

from __future__ import annotations

import pytest
from policy_pages_support import BASE, write_fake
from review_browser_support import Served
from review_fakes import FakeRuns

from fsi_common.app.browser_checks import type_floor_problems

SIZES = ((1366, 768), (1920, 1080))
HEADINGS = """
() => [...document.querySelectorAll('table.policy-grid')].map(table => {
  const heads = [...table.querySelectorAll('th.doc-head')].map(th => {
    const box = th.getBoundingClientRect();
    const inner = [...th.querySelectorAll('.doc-title, .doc-version')].map(el => {
      const range = document.createRange();
      range.selectNodeContents(el);
      const text = range.getBoundingClientRect();
      return {right: text.right, left: text.left, text: el.textContent};
    });
    return {left: box.left, right: box.right, inner};
  });
  return heads;
})
"""


@pytest.fixture()
def served(tmp_path, monkeypatch):
    _, root = write_fake(tmp_path)
    monkeypatch.setenv("POLICY_BUNDLES_DIR", str(root))
    server = Served(FakeRuns())
    yield server
    server.stop()


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_the_documents_headings_of_the_picture_do_not_overlap_and_stay_in_their_columns(
    browser, served, size
):
    context, page = served.open(browser, size)
    page.goto(served.base_url + BASE)
    tables = page.evaluate(HEADINGS)
    assert len(tables) == 3
    for heads in tables:
        assert len(heads) == 6
        for before, after in zip(heads, heads[1:], strict=False):
            assert before["right"] <= after["left"] + 1, "two headings share the same space"
        for head in heads:
            for part in head["inner"]:
                assert part["left"] >= head["left"] - 1, part["text"]
                assert part["right"] <= head["right"] + 1, f"{part['text']} runs past its column"
    assert type_floor_problems(page) == []
    context.close()
