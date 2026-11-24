"""The offline file opened from disk in a real browser with every outside request blocked."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from review_offline_support import RealExport, make_export

SIZE = {"width": 1366, "height": 768}
VISIBLE = """
() => [...document.querySelectorAll('.offline-page')]
  .filter(p => getComputedStyle(p).display !== 'none')
  .map(p => ({
    id: p.id,
    sentence: p.querySelector('[data-hook="sentence"]')?.innerText ?? '',
    tiles: p.querySelectorAll('[data-hook="tile"]').length,
    exhibits: p.querySelectorAll('[data-hook="exhibit"]').length,
    demo: p.querySelector('[data-hook="demo-tag"]')?.innerText ?? '',
  }))
"""
FOLLOW = """
([pageId, href]) => {
  location.hash = '#' + pageId;
  const link = [...document.querySelectorAll(`#${pageId} a`)].find(a => a.getAttribute('href') === href);
  if (!link) return {missing: true};
  link.click();
  const shown = [...document.querySelectorAll('.offline-page')]
    .filter(p => getComputedStyle(p).display !== 'none')
    .map(p => ({id: p.id, sentence: p.querySelector('[data-hook="sentence"]')?.innerText ?? ''}));
  return {missing: false, hash: location.hash, shown};
}
"""  # noqa: E501


@pytest.fixture(scope="module")
def real(tmp_path_factory) -> RealExport:
    return make_export(tmp_path_factory.mktemp("offline-browser") / "brief.html")


@pytest.fixture()
def offline(browser, real):
    """The file opened from disk; every request that is not for a file is refused and counted."""
    context = browser.new_context(viewport=SIZE, accept_downloads=True)
    seen, refused, errors = [], [], []

    def gate(route):
        url = route.request.url
        if url.startswith("file:"):
            route.continue_()
        else:
            refused.append(url)
            route.abort()

    context.route("**/*", gate)
    context.on("request", lambda r: seen.append(r.url))
    page = context.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    yield page, seen, refused, errors
    context.close()


def url_of(real: RealExport, page_id: str = "") -> str:
    return real.path.resolve().as_uri() + (f"#{page_id}" if page_id else "")


def test_the_file_opens_from_disk_on_the_review_page_with_no_request_but_the_file(offline, real):
    page, seen, refused, errors = offline
    page.goto(url_of(real))
    shown = page.evaluate(VISIBLE)
    assert [s["id"] for s in shown] == [real.export.ids[real.export.entry]]
    assert shown[0]["sentence"] == real.sentence(real.export.entry)
    assert shown[0]["demo"] == "Demo"
    assert refused == []
    assert all(u.startswith("file:") for u in seen), seen
    assert errors == []


def test_every_page_opens_by_its_address_and_shows_its_own_sentence(offline, real):
    page, seen, refused, errors = offline
    for address in real.export.addresses:
        page_id = real.export.ids[address]
        page.goto(url_of(real, page_id))
        shown = page.evaluate(VISIBLE)
        assert [s["id"] for s in shown] == [page_id], address
        assert shown[0]["sentence"] == real.sentence(address), address
        assert 0 <= shown[0]["tiles"] <= 3 and shown[0]["demo"] == "Demo", address
    assert refused == [] and errors == []
    assert all(u.startswith("file:") for u in seen)


def test_every_link_in_the_file_leads_to_the_page_it_names(offline, real):
    page, seen, refused, errors = offline
    sentences = {real.export.ids[a]: real.sentence(a) for a in real.export.addresses}
    page.goto(url_of(real))
    followed = 0
    for address in real.export.addresses:
        page_id = real.export.ids[address]
        hrefs = page.eval_on_selector_all(
            f"#{page_id} a[href^='#']", "els => [...new Set(els.map(e => e.getAttribute('href')))]"
        )
        for href in hrefs:
            result = page.evaluate(FOLLOW, [page_id, href])
            assert not result["missing"], (address, href)
            target = re.match(r"#(page-.*?)(--.*)?$", href).group(1)
            assert result["hash"] == href, (address, href)
            assert [s["id"] for s in result["shown"]] == [target], (address, href)
            assert result["shown"][0]["sentence"] == sentences[target], (address, href)
            followed += 1
    assert followed > len(real.export.addresses)
    assert refused == [] and errors == []
    assert all(u.startswith("file:") for u in seen), seen


def test_a_real_click_on_a_cited_fact_opens_its_paragraph_in_the_file(offline, real):
    page, seen, refused, errors = offline
    page.goto(url_of(real))
    first = page.locator(".offline-page:visible a.fact-link").nth(1)
    target = first.get_attribute("href")
    first.click()
    assert page.evaluate("location.hash") == target
    shown = page.evaluate(VISIBLE)
    assert [s["id"] for s in shown] == [target[1:]]
    visible = ".offline-page:visible"
    source = f"{visible} [data-hook='paragraph'], {visible} [data-hook='row-table']"
    paragraph = page.locator(source).inner_text()
    assert paragraph.strip()
    assert refused == []


def test_the_csv_export_of_the_facts_table_downloads_the_rows_the_server_gives(offline, real):
    page, seen, refused, errors = offline
    facts = real.export.entry.replace("/review", "/facts")
    page.goto(url_of(real, real.export.ids[facts]))
    with page.expect_download() as download:
        page.locator(".offline-page:visible [data-hook='export']").click()
    saved = Path(download.value.path()).read_bytes().decode("utf-8")
    served = real.client.get(facts.replace("/facts", "/facts.csv")).content.decode("utf-8")
    assert saved == served
    assert saved.count("\r\n") > 2
    assert refused == []


def test_the_forms_show_and_their_buttons_cannot_be_pressed(offline, real):
    page, seen, refused, errors = offline
    page.goto(url_of(real))
    button = page.get_by_role("button", name="Record my decision")
    assert button.count() == 1 and button.is_disabled()
    page.goto(url_of(real, real.export.ids[f"{real.export.entry}?tab=signoff"]))
    assert (
        page.locator(".offline-page:visible [data-hook='signoff-form'] button[disabled]").count()
        == 2
    )
    assert refused == []


def test_a_request_to_the_network_would_be_refused_and_counted(offline, real):
    """The planted fault: the guard must see an outside request, or the others prove nothing."""
    page, seen, refused, errors = offline
    page.goto(url_of(real))
    page.evaluate("fetch('http://example.invalid/x').catch(() => null)")
    page.wait_for_timeout(200)
    assert refused == ["http://example.invalid/x"]


def test_a_link_to_a_page_that_is_not_in_the_file_is_told_apart(offline, real, tmp_path):
    """The planted fault for the link check: the page it asks for is not the page that shows."""
    broken = tmp_path / "broken.html"
    broken.write_text(
        real.export.html.replace('href="#page-about"', 'href="#page-missing"'), encoding="utf-8"
    )
    page, seen, refused, errors = offline
    page.goto(broken.resolve().as_uri())
    entry = real.export.ids[real.export.entry]
    result = page.evaluate(FOLLOW, [entry, "#page-missing"])
    assert not result["missing"]
    assert [s["id"] for s in result["shown"]] != ["page-missing"]
