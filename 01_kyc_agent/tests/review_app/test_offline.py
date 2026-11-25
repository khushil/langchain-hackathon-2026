"""The offline edition: every page of the topic in one file that opens with the network blocked."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from kyc_fakes import ScriptedReader

from fsi_common.app.offline import export_pages, replay_only
from review_app import offline, service

SIZE = {"width": 1366, "height": 768}
VISIBLE = """
() => [...document.querySelectorAll('.offline-page')]
  .filter(p => getComputedStyle(p).display !== 'none')
  .map(p => ({id: p.id, sentence: p.querySelector('[data-hook="sentence"]')?.innerText ?? ''}))
"""


@pytest.fixture(scope="module")
def export():
    service.use_models(ScriptedReader())
    try:
        with replay_only():
            yield export_pages(offline.build_app(), offline.seed)
    finally:
        service.use_models(None)


@pytest.fixture(scope="module")
def written(export, tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("offline") / "kyc.html"
    path.write_text(export.html, encoding="utf-8")
    return path


def test_the_file_holds_both_batches_every_application_and_the_tables(export):
    addresses = export.addresses
    reviews = [a for a in addresses if a.endswith("/review")]
    signed = [a for a in addresses if a.endswith("/signed")]
    assert len(reviews) == 1 and len(signed) == 1
    assert len([a for a in addresses if "/applications/CUST-" in a]) == 50
    assert sum(a.endswith("/screenings") for a in addresses) == 2
    assert export.csv_files >= 4
    assert "/kyc/" in addresses


def controls_in(html: str) -> list[str]:
    """Name each control or sign-out wording that a page of the file must not hold."""
    found = [tag for tag in ("<form", "<button", "<textarea", "<input") if tag in html]
    found += [text for text in ("Sign out", "Record my decision") if text in html]
    found += re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", html)
    return found


def test_no_page_of_the_file_has_a_form_a_button_or_a_sign_out(export):
    assert controls_in(export.html) == []


def test_the_signed_batch_in_the_file_shows_the_fictional_reviewer(export):
    signed = next(a for a in export.addresses if a.endswith("/signed"))
    assert export.ids[signed] in export.html
    assert "Dana Whitfield, Head of Compliance" in export.html


@pytest.fixture()
def offline_page(browser, written):
    context = browser.new_context(viewport=SIZE)
    seen, refused, errors = [], [], []

    def gate(route):
        if route.request.url.startswith("file:"):
            route.continue_()
        else:
            refused.append(route.request.url)
            route.abort()

    context.route("**/*", gate)
    context.on("request", lambda r: seen.append(r.url))
    page = context.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    yield page, seen, refused, errors
    context.close()


def test_the_file_opens_from_disk_on_the_waiting_batch_with_no_request_but_the_file(
    offline_page, written, export
):
    page, seen, refused, errors = offline_page
    page.goto(written.resolve().as_uri())
    shown = page.evaluate(VISIBLE)
    assert [s["id"] for s in shown] == [export.ids[export.entry]]
    assert "25 applications were screened against 14 list entries" in shown[0]["sentence"]
    assert page.locator(".offline-page:visible [data-hook=picture-row]").count() == 25
    assert refused == [] and errors == []
    assert all(u.startswith("file:") for u in seen)


def test_a_real_click_on_a_cell_opens_the_application_inside_the_file(offline_page, written):
    page, seen, refused, errors = offline_page
    page.goto(written.resolve().as_uri())
    cell = page.locator(".offline-page:visible a[data-hook=picture-cell][data-state=needs]").first
    target = cell.get_attribute("href")
    cell.click()
    assert page.evaluate("location.hash") == target
    shown = page.evaluate(VISIBLE)
    assert [s["id"] for s in shown] == [target[1:]]
    assert "proposed" in shown[0]["sentence"]
    assert page.locator(".offline-page:visible [data-hook=reading-same]").count() >= 1
    assert refused == []


def test_the_offline_guard_sees_a_request_to_the_network(offline_page, written):
    """The planted fault: the guard must see an outside request, or the others prove nothing."""
    page, seen, refused, errors = offline_page
    page.goto(written.resolve().as_uri())
    page.evaluate("fetch('http://example.invalid/x').catch(() => null)")
    page.wait_for_timeout(200)
    assert refused == ["http://example.invalid/x"]


@pytest.mark.parametrize(
    ("plant", "expected"),
    [
        ('<form method="post"></form>', "<form"),
        ("<button>Go</button>", "<button"),
        ("<p>Sign out</p>", "Sign out"),
        ("<p>5d0ab1c2-aaaa-bbbb-cccc-0123456789ab</p>", "5d0ab1c2-aaaa-bbbb-cccc-0123456789ab"),
    ],
)
def test_the_check_on_the_file_finds_each_control_planted_into_it(export, plant, expected):
    assert controls_in(export.html) == []
    planted = export.html.replace("</body>", f"{plant}</body>")
    assert expected in controls_in(planted)
