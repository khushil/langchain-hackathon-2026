"""The offline file for a real brief on replay: every page, every paragraph, nothing outside."""

from __future__ import annotations

import html
import os
import re

import pytest
from review_offline_support import RealExport, body_text, make_export, section_html

from fsi_common.app.offline import OfflineExportError, export_pages, replay_only
from fsi_common.model import ReplayMissError
from review_app.offline import HOOK
from review_app.plugin import ABOUT

RECORDINGS = os.path.join(os.path.dirname(__file__), "..", "..", "recordings")
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
    return make_export(tmp_path_factory.mktemp("offline") / "brief.html")


def served_review(real: RealExport) -> str:
    return real.served(real.export.entry)


def cited_fact_links(real: RealExport) -> dict[str, str]:
    """Where each cited fact opens, read from the links of the served review page."""
    found = re.findall(r'href="([^"]+)" data-fact="([^"]+)"', served_review(real))
    return {fact: html.unescape(href) for href, fact in found}


def test_the_file_holds_every_cited_fact_with_the_paragraph_it_rests_on(real):
    facts = cited_fact_links(real)
    assert facts, "the replayed brief cites no fact, so there is nothing to compare"
    with_paragraph = 0
    for fact, address in facts.items():
        assert address in real.export.addresses, f"{fact} has no page in the file"
        panel = re.search(
            r'data-hook="paragraph">(.*?)</p>|data-hook="row-table">(.*?)</table>',
            real.served(address),
            re.S,
        )
        assert panel, fact
        words = body_text(f"<html><body>{panel.group(1) or panel.group(2)}</body></html>")
        section = body_text(section_html(real.export.html, real.export.ids[address]))
        assert words and words in section, f"the paragraph of {fact} is not on its page"
        with_paragraph += 1
    assert with_paragraph == len(facts)


def test_every_page_the_export_reached_is_in_the_file_with_the_words_the_server_shows(real):
    sections = re.findall(r'<div class="offline-page" id="([^"]+)"', real.export.html)
    assert sorted(sections) == sorted(real.export.ids.values())
    assert len(sections) == len(real.export.addresses) == len(set(sections))
    for address in real.export.addresses:
        file_words = body_text(section_html(real.export.html, real.export.ids[address]))
        assert file_words == body_text(real.served(address)), address


def test_the_pages_include_the_shell_the_review_the_questions_the_sign_off_and_the_facts(real):
    addresses = real.export.addresses
    entry = real.export.entry
    assert entry.endswith("/review") and addresses[0] == entry
    for wanted in ("/", "/about", "/compliance-brief/", f"{entry}?tab=questions"):
        assert wanted in addresses, wanted
    assert f"{entry}?tab=signoff" in addresses
    assert entry.replace("/review", "/facts") in addresses
    assert not any(a.endswith("/signed") for a in addresses)


def test_every_table_has_its_sort_links_and_its_export_in_the_file(real):
    sorts = [a for a in real.export.addresses if "sort=" in a]
    assert sorts
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


def test_the_forms_are_there_and_cannot_submit(real):
    text = real.export.html
    assert "Record my decision" in text
    forms = re.findall(r"<form[^>]*>(.*?)</form>", text, flags=re.S)
    assert forms
    for form in forms:
        for button in re.findall(r"<button[^>]*>", form):
            assert " disabled" in button, button
    assert "/compliance-brief/runs/" not in " ".join(re.findall(r"<form[^>]*>", text))


def test_the_same_recordings_export_to_the_same_bytes(real, tmp_path):
    again = make_export(tmp_path / "again.html")
    assert again.export.html == real.export.html


def test_the_export_makes_no_call_that_a_recording_does_not_answer(real):
    before = sorted(os.listdir(RECORDINGS))
    make_export(real.path.parent / "third.html")
    assert sorted(os.listdir(RECORDINGS)) == before
    assert before, "there are no recordings to answer from"


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
        assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
    assert os.environ["MODEL_BACKEND"] == "claude-code"
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert "LANGCHAIN_TRACING_V2" not in os.environ


def test_a_start_that_the_application_refuses_is_named(real):
    unsigned = real.client.__class__(real.client.app, follow_redirects=False)
    with pytest.raises(OfflineExportError, match="start route answered 403"):
        HOOK.seed(unsigned)
