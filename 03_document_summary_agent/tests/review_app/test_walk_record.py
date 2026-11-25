"""The record of a finished brief: its statements, their sources read-only, its digest label."""

from __future__ import annotations

import re

import pytest
from review_fakes import FakeRuns
from review_fixtures import DANA, make_client
from review_helpers import RUN, accept_on, finish, text_of

from fsi_common.examples.data import build_examples

EX = build_examples()
BOTH = [accept_on(EX.fact_7_1, DANA, "2026-11-25"), accept_on(EX.fact_9_3, DANA, "2026-11-25")]


def finished(outcome: str) -> FakeRuns:
    runs = FakeRuns()
    finish(runs, "run-1", BOTH, DANA, on="2026-11-25", outcome=outcome)
    return runs


def test_a_signed_record_labels_its_digest_signed():
    page = make_client(finished("signed")).get(f"{RUN}/signed")
    text = text_of(page.text)
    assert "Digest signed" in text and "Digest returned" not in text


def test_a_returned_record_labels_its_digest_returned():
    page = make_client(finished("returned")).get(f"{RUN}/signed")
    text = text_of(page.text)
    assert "Digest returned" in text and "Digest signed" not in text


@pytest.mark.parametrize("outcome", ["signed", "returned"])
@pytest.mark.parametrize("viewer", [DANA, None], ids=["signed in", "visitor"])
def test_the_record_shows_every_statement_with_the_facts_it_cites(outcome, viewer):
    runs = finished(outcome)
    review = runs._runs["run-1"].review
    page = make_client(runs, signed_in=viewer).get(f"{RUN}/signed")
    text = text_of(page.text)
    for statement in review.request.statements:
        assert statement.text in text
        assert statement.heading in text
    cited = [c.fact.id for s in review.request.statements for c in s.facts]
    assert re.findall(r'data-fact="([^"]+)"', page.text) == cited
    assert "Accepted by" in text


@pytest.mark.parametrize("outcome", ["signed", "returned"])
def test_every_cited_fact_on_the_record_opens_its_source_with_no_way_to_decide(outcome):
    runs = finished(outcome)
    client = make_client(runs)
    review = runs._runs["run-1"].review
    for statement in review.request.statements:
        for cited in statement.facts:
            page = client.get(f"{RUN}/signed", params={"fact": cited.fact.id})
            assert page.status_code == 200
            assert 'data-hook="source"' in page.text
            marked = re.findall(r"<mark>(.*?)</mark>", page.text, flags=re.S)
            assert [m.replace("&#39;", "'") for m in marked] == [cited.fact.quote]
            assert "Document digest" in page.text
            assert cited.fact.provenance.as_of in page.text
            assert "Reason given: Read by Dana Whitfield." in text_of(page.text)
            for control in ("decision-form", "<textarea", 'name="outcome"', "Record my decision"):
                assert control not in page.text


def test_the_source_of_a_finished_brief_opens_on_the_first_fact_when_none_is_named():
    runs = finished("signed")
    first = runs._runs["run-1"].review.request.statements[0].facts[0].fact
    page = make_client(runs).get(f"{RUN}/signed")
    assert f'data-fact="{first.id}" ' in page.text and 'aria-current="true"' in page.text
    assert first.quote in re.findall(r"<mark>(.*?)</mark>", page.text, flags=re.S)


@pytest.mark.parametrize("outcome", ["signed", "returned"])
def test_the_facts_table_of_a_finished_brief_links_each_fact_to_its_source_read_only(outcome):
    runs = finished(outcome)
    client = make_client(runs)
    review = runs._runs["run-1"].review
    page = client.get(f"{RUN}/facts")
    links = re.findall(r'<a href="([^"]+)" title="Open [^"]+quoted words"', page.text)
    cited = [c.fact.id for s in review.request.statements for c in s.facts]
    assert len(links) == len(cited)
    for href, fact_id in zip(links, cited, strict=True):
        assert "/signed?" in href and fact_id.replace(":", "%3A") in href
        opened = client.get(href.split("#")[0].replace("&amp;", "&"))
        assert opened.status_code == 200 and 'data-hook="source"' in opened.text
        assert "decision-form" not in opened.text


def _position(html: str, marker: str) -> int:
    found = html.find(marker)
    assert found >= 0, marker
    return found


def test_the_finished_page_reads_outcome_then_the_brief_then_the_record_then_the_decisions():
    page = make_client(finished("signed")).get(f"{RUN}/signed").text
    order = [
        _position(page, 'data-hook="sentence"'),
        _position(page, 'data-hook="statements"'),
        _position(page, 'data-hook="sign-off-record"'),
        _position(page, 'aria-label="Decisions made on the brief"'),
    ]
    assert order == sorted(order)


def test_the_record_shows_the_digest_shortened_with_the_whole_value_on_hover_and_focus():
    runs = finished("signed")
    full = runs._runs["run-1"].review.request.brief_digest
    whole = make_client(runs).get(f"{RUN}/signed").text
    page = whole[whole.index('data-hook="sign-off-record"') :]
    summary = re.search(r'<summary[^>]*class="digest"[^>]*>(.*?)</summary>', page, flags=re.S)
    assert summary, "the digest is not a control that can take focus"
    assert f'title="{full}"' in summary.group(0)
    shown = text_of(summary.group(1)).strip()
    assert shown == full[:15] + "…" and len(shown) < len(full)
    assert page.count(full) == 2  # the hover title and the whole value in the opened details
