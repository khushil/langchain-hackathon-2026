"""The offline file opened from disk in a real browser with every outside request blocked."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from review_offline_support import RealExport, make_export, section_html

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

FOLLOW_DISTINCT = """
(pageIds) => {
  const premise = {
    scripts: document.querySelectorAll('script').length,
    handlers: [...document.querySelectorAll('*')]
      .filter(e => [...e.attributes].some(a => /^on/i.test(a.name))).length,
    targeted: document.querySelectorAll('a[target]').length,
    fragmentDownloads: document.querySelectorAll("a[href^='#'][download]").length,
    otherLinks: [...document.querySelectorAll('a')]
      .filter(a => !(a.getAttribute('href') ?? '').startsWith('#') && !a.hasAttribute('download'))
      .length,
    scriptUrls: document.querySelectorAll("a[href^='javascript:' i]").length,
  };
  const pairs = [];
  const followed = [];
  const seen = new Set();
  for (const pageId of pageIds) {
    const own = [...document.querySelectorAll(`#${pageId} a`)];
    const hrefs = [...new Set(own.map(a => a.getAttribute('href')).filter(h => h?.startsWith('#')))];
    for (const href of hrefs) {
      const link = own.find(a => a.getAttribute('href') === href);
      const named = href.match(/^#(page-.*?)(--.*)?$/);
      pairs.push({page: pageId, href, present: !!link, target: !!named && !!document.getElementById(named[1])});
      if (!link || seen.has(href)) continue;
      seen.add(href);
      location.hash = '#' + pageId;
      if (location.hash === href) location.hash = '';
      link.click();
      const shown = [...document.querySelectorAll('.offline-page')]
        .filter(p => getComputedStyle(p).display !== 'none')
        .map(p => ({id: p.id, sentence: p.querySelector('[data-hook="sentence"]')?.innerText ?? ''}));
      followed.push({page: pageId, href, missing: false, hash: location.hash, shown});
    }
  }
  return {premise, pairs, followed};
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


def follow_links(page, page_ids: list[str]) -> dict:
    """Check the file's premise, every (page, href) pair, and one real click per distinct href."""
    return page.evaluate(FOLLOW_DISTINCT, page_ids)


def link_faults(records: list[dict], sentences: dict[str, str], addresses: dict[str, str]) -> list:
    """Return one line per link that fails the four checks, naming its page address and href."""
    faults = []
    for record in records:
        where = (addresses[record["page"]], record["href"])
        if record["missing"]:
            faults.append((*where, "the link is not on its page"))
            continue
        target = re.match(r"#(page-.*?)(--.*)?$", record["href"]).group(1)
        if record["hash"] != record["href"]:
            faults.append((*where, f"the hash is {record['hash']!r}"))
        elif [s["id"] for s in record["shown"]] != [target]:
            faults.append((*where, f"the pages shown are {[s['id'] for s in record['shown']]}"))
        elif record["shown"][0]["sentence"] != sentences[target]:
            faults.append((*where, "the page shown has another sentence"))
    return faults


def links_in_file(html: str, page_ids: list[str]) -> list[tuple[str, str]]:
    """Read the file's own text for every (page, address) pair of in-file links, to count them."""
    pairs = []
    for page_id in page_ids:
        section = section_html(html, page_id)
        hrefs = dict.fromkeys(re.findall(r"<a\b[^>]*?\bhref=\"(#[^\"]*)\"", section))
        pairs.extend((page_id, href) for href in hrefs)
    return pairs


def test_every_link_in_the_file_leads_to_the_page_it_names(offline, real):
    page, seen, refused, errors = offline
    ids = {real.export.ids[a]: a for a in real.export.addresses}
    sentences = {i: real.sentence(a) for i, a in ids.items()}
    page.goto(url_of(real))
    found = follow_links(page, list(ids))
    # With no script and no handler, the page a link shows depends on its href alone.
    premise = found["premise"]
    assert premise == {
        "scripts": 0,
        "handlers": 0,
        "targeted": 0,
        "fragmentDownloads": 0,
        "otherLinks": 0,
        "scriptUrls": 0,
    }, premise
    pairs = links_in_file(real.path.read_text(encoding="utf-8"), list(ids))
    assert [(r["page"], r["href"]) for r in found["pairs"]] == pairs
    assert len(pairs) > len(ids)
    gone = [
        (ids[r["page"]], r["href"]) for r in found["pairs"] if not (r["present"] and r["target"])
    ]
    assert gone == []
    distinct = list(dict.fromkeys(href for _, href in pairs))
    assert [r["href"] for r in found["followed"]] == distinct
    assert link_faults(found["followed"], sentences, ids) == []
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


def test_no_page_shows_a_form_a_button_or_a_sign_out(offline, real):
    page, seen, refused, errors = offline
    for address in real.export.addresses:
        page.goto(url_of(real, real.export.ids[address]))
        controls = page.evaluate("['button', 'form'].map(t => document.querySelectorAll(t).length)")
        assert controls == [0, 0], address
    # The file is one document that holds every page, hidden or shown, and a text locator counts
    # over the whole document whatever page is open, so the two phrases are counted once.
    # Counting them again at each of the 106 addresses re-scanned 7.5 MB of the same DOM each time.
    assert page.get_by_text("Sign out").count() == 0
    assert page.get_by_text("Record my decision").count() == 0
    # Playwright's locators reach into shadow roots, where querySelectorAll does not.
    assert page.locator("button").count() == 0
    assert page.locator("form").count() == 0
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
