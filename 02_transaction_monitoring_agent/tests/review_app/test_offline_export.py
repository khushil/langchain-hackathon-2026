"""The offline file for transaction monitoring: every page, every transaction, nothing outside."""

from __future__ import annotations

import html
import os
import re

import pytest
from engine_fakes import ScriptedModels
from review_offline_support import RealExport, body_text, make_export, section_html

from fsi_common.app.offline import OfflineExportError, export_pages, replay_only
from fsi_common.model import ReplayMissError
from review_app.offline import HOOK, build_app
from review_app.plugin import ABOUT

OUTSIDE = (
    r"https?://",
    r"\burl\(",
    r"@import",
    r"\b(?:src|srcset|poster|action)=",
    r"/(?:home|Users|root)/\w",
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
    r"<script",
    r"<img",
    r"<link",
)


@pytest.fixture(scope="module")
def real(tmp_path_factory) -> RealExport:
    return make_export(tmp_path_factory.mktemp("offline") / "monitoring.html")


def served_review(real: RealExport) -> str:
    return real.served(real.export.entry)


def transaction_links(real: RealExport) -> dict[str, str]:
    """Where each transaction of the brief opens, read from the links of the served review page."""
    found = re.findall(r'href="([^"]+)" data-fact="([^"]+)"', served_review(real))
    return {fact: html.unescape(href) for href, fact in found}


def test_the_file_holds_every_transaction_of_the_brief_with_the_line_it_rests_on(real):
    links = transaction_links(real)
    assert len(links) == 10, "the waiting run covers the customer's ten transactions"
    for fact, address in links.items():
        assert address in real.export.addresses, f"{fact} has no page in the file"
        panel = re.search(r'data-hook="source-line">(.*?)</p>', real.served(address), re.S)
        assert panel, fact
        words = body_text(f"<html><body>{panel.group(1)}</body></html>")
        section = body_text(section_html(real.export.html, real.export.ids[address]))
        assert words and words in section, f"the source line of {fact} is not on its page"


def test_every_page_the_export_reached_is_in_the_file_with_the_words_the_server_shows(real):
    sections = re.findall(r'<div class="offline-page" id="([^"]+)"', real.export.html)
    assert sorted(sections) == sorted(real.export.ids.values())
    assert len(sections) == len(real.export.addresses) == len(set(sections))
    for address in real.export.addresses:
        file_words = body_text(section_html(real.export.html, real.export.ids[address]))
        assert file_words == body_text(real.served_without_controls(address)), address


def test_the_pages_include_the_shell_the_review_its_parts_and_the_signed_run(real):
    addresses = real.export.addresses
    entry = real.export.entry
    assert entry.endswith("/review") and addresses[0] == entry
    for wanted in ("/", "/about", "/transaction-monitoring/"):
        assert wanted in addresses, wanted
    for tab in ("questions", "history", "signoff"):
        assert f"{entry}?tab={tab}" in addresses
    assert sum("/signed" in a for a in addresses) >= 1


def test_every_table_has_its_sort_links_and_its_export_in_the_file(real):
    assert [a for a in real.export.addresses if "sort=" in a]
    assert real.export.csv_files >= 2
    assert "download=" in real.export.html


def test_nothing_in_the_file_points_outside_it(real):
    text = real.export.html
    for pattern in OUTSIDE:
        assert re.search(pattern, text) is None, pattern
    for href in re.findall(r'\shref="([^"]*)"', text):
        assert href.startswith("#") or href.startswith("data:text/csv"), href


def test_the_demo_tag_and_about_are_the_served_ones_and_nothing_is_added(real):
    text = real.export.html
    assert text.count('data-hook="demo-tag"') == len(real.export.addresses)
    about = body_text(section_html(text, real.export.ids["/about"]))
    for paragraph in ABOUT:
        assert paragraph in about
    for note in ("offline", "snapshot", "exported", "no network"):
        assert note not in body_text(text).lower()


def test_no_page_of_the_file_has_a_form_a_button_or_a_sign_out(real):
    text = real.export.html
    for part in ("<form", "<button", "<textarea", 'type="submit"'):
        assert part not in text, part
    assert not re.search(r"<[a-z][^>]*\sdisabled", text)
    assert "Sign out" not in text and "Record my decision" not in text
    assert "/transaction-monitoring/runs/" not in text.replace('href="#', "")


def test_the_list_page_has_no_start_panel_without_its_form(real):
    assert "Assess a customer's transactions" in html.unescape(
        real.served("/transaction-monitoring/")
    )
    assert "Assess a customer" not in html.unescape(real.export.html)


def test_every_page_still_shows_the_decisions_and_the_source_read_only(real):
    text = real.export.html
    assert text.count('data-hook="source"') >= 1 and "<mark>" in text
    assert "Carried: agreed" in text and "Table digest" in text
    for address in real.export.addresses:
        assert real.export.ids[address] in text


def test_the_picture_of_every_page_is_in_the_file_with_its_marks_as_links(real):
    text = real.export.html
    assert text.count('data-hook="stream"') >= len(real.export.addresses) // 2
    assert 'class="stream-svg"' in text and 'data-hook="mark"' in text
    marks = re.findall(r'<a href="#[^"]+" title="[^"]+" aria-label="[^"]+" data-tx="TX-\d+"', text)
    assert len(marks) >= 10


def test_the_same_inputs_export_to_the_same_bytes(real, tmp_path):
    again = make_export(tmp_path / "again.html")
    assert again.export.html == real.export.html


def test_a_missing_recording_stops_the_export_with_the_request_hash(monkeypatch, tmp_path):
    empty = tmp_path / "recordings"
    empty.mkdir()
    monkeypatch.setenv("MODEL_RECORDINGS_DIR", str(empty))
    with pytest.raises(ReplayMissError, match=r"no recording for request [0-9a-f]{64}"):
        export_pages(HOOK.build_app(), HOOK.seed)
    assert list(empty.iterdir()) == []


def test_the_replay_settings_hold_in_the_block_and_are_put_back(monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "claude-code")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    with replay_only():
        assert os.environ["MODEL_BACKEND"] == "replay"
        assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["MODEL_BACKEND"] == "claude-code"
    assert os.environ["LANGSMITH_TRACING"] == "true"


def test_a_start_that_leaves_no_run_waiting_is_named(real, monkeypatch):
    monkeypatch.setattr("review_app.offline.seed_transaction_monitoring", lambda *args: None)
    fresh = build_app(ScriptedModels())
    client = real.client.__class__(fresh, follow_redirects=False)
    with pytest.raises(OfflineExportError, match="left no run waiting for a reviewer"):
        HOOK.seed(client)
