"""The picture of the document: its paragraphs in order, each marked by what was found in it."""

from __future__ import annotations

import re

import pytest
from review_fakes import FakeRuns, section_seven_review
from review_fixtures import DANA, TODAY, make_client
from review_helpers import RUN, accept_on, text_of
from review_map_fakes import NO_FACT, map_review

from fsi_common.records import SignOff

NUMBERS = ["6.1", "6.2", "7.1", "7.2", "7.3", "7.4", "7.5"]
MARKS = {
    "6.1": "No fact",
    "6.2": "Failed check",
    "7.1": "Open question",
    "7.2": "Obligation, deadline",
    "7.3": "Obligation, deadline",
    "7.4": "Obligation",
    "7.5": "Permission",
}


@pytest.fixture()
def map_runs() -> FakeRuns:
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=map_review())
    return runs


def cells(html: str) -> list[dict]:
    found = re.findall(
        r'<a class="map-cell map-(\w+)" href="([^"]+)" data-para="([^"]+)" title="([^"]*)"[^>]*>'
        r'\s*<span class="map-number">[^<]*</span>\s*<span class="map-mark">(.*?)</span>',
        html,
        flags=re.S,
    )
    return [
        {
            "kind": k,
            "href": h.replace("&amp;", "&"),
            "number": n,
            "title": t,
            "mark": text_of(m).strip(),
        }
        for k, h, n, t, m in found
    ]


def test_the_review_page_opens_on_a_picture_of_the_paragraphs_read_in_order(map_runs):
    page = make_client(map_runs).get(f"{RUN}/review")
    assert 'data-hook="map"' in page.text
    assert [c["number"] for c in cells(page.text)] == NUMBERS
    assert page.text.index('data-hook="map"') < page.text.index('data-hook="statements"')
    text = text_of(page.text)
    assert "6. Third-party technology providers" in text and "7. Incident reporting" in text


def test_each_paragraph_is_marked_by_a_word_for_what_was_found_in_it(map_runs):
    found = cells(make_client(map_runs).get(f"{RUN}/review").text)
    assert {c["number"]: c["mark"] for c in found} == MARKS
    assert {c["number"]: c["kind"] for c in found} == {
        "6.1": "nothing",
        "6.2": "failed",
        "7.1": "question",
        "7.2": "obligation",
        "7.3": "obligation",
        "7.4": "obligation",
        "7.5": "other",
    }
    assert all(c["mark"] for c in found)


def test_only_a_question_or_a_failed_check_takes_an_alert_colour(map_runs):
    css = make_client(map_runs).get("/compliance-brief/static/review.css").text.replace("\n", " ")
    for kind, alert in (("question", "amber"), ("failed", "coral")):
        assert re.search(rf"\.map-{kind}\s*\{{[^}}]*--{alert}", css), kind
    for kind in ("nothing", "obligation", "other"):
        assert not re.search(rf"\.map-{kind}\s*\{{[^}}]*--(amber|coral)", css), kind


def test_the_count_that_closes_reads_from_the_accounting_of_the_run(map_runs):
    page = make_client(map_runs).get(f"{RUN}/review")
    state = map_runs.result("run-1")
    [accounting] = state["accounting"].values()
    expected = len(accounting["with_facts"]) + len(accounting["without_facts"])
    assert expected == accounting["units_in"] == 7
    assert "7 of 7 paragraphs of sections 6 and 7 accounted for" in text_of(page.text)


def test_a_run_of_one_section_names_that_section_in_the_count():
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=section_seven_review())
    page = make_client(runs).get(f"{RUN}/review")
    assert "5 of 5 paragraphs of section 7 accounted for" in text_of(page.text)


def test_a_paragraph_with_a_fact_opens_its_source_and_one_without_opens_the_paragraph_and_why(
    map_runs,
):
    client = make_client(map_runs)
    by_number = {c["number"]: c for c in cells(client.get(f"{RUN}/review").text)}
    with_fact = client.get(by_number["7.2"]["href"])
    assert "Paragraph 7.2" in text_of(with_fact.text) and "<mark>" in with_fact.text
    assert 'aria-current="true"' in with_fact.text
    without = client.get(by_number["6.1"]["href"])
    text = text_of(without.text)
    assert without.status_code == 200 and "Paragraph 6.1" in text
    assert NO_FACT in text and "<mark>" not in without.text
    assert "decision-form" not in without.text
    failed = client.get(by_number["6.2"]["href"])
    assert "Paragraph 6.2" in text_of(failed.text) and "<mark>" not in failed.text


def test_the_facts_page_leads_with_the_picture_and_keeps_the_table_below(map_runs):
    client = make_client(map_runs)
    page = client.get(f"{RUN}/facts")
    assert [c["number"] for c in cells(page.text)] == NUMBERS
    assert page.text.index('data-hook="map"') < page.text.index('data-hook="table"')
    assert "7 of 7 paragraphs of sections 6 and 7 accounted for" in text_of(page.text)
    link = next(c for c in cells(page.text) if c["number"] == "7.3")
    assert client.get(link["href"]).status_code == 200


def finished(runs: FakeRuns) -> None:
    review = runs._runs["run-1"].review
    facts = [c.fact for s in review.request.statements for c in s.facts]
    run = runs._runs["run-1"]
    run.state["decisions"] = {d.id: d.to_json() for d in (accept_on(f, DANA, TODAY) for f in facts)}
    run.state["sign_off"] = SignOff.build(
        brief_id=review.request.brief_id,
        brief_digest=review.request.brief_digest,
        reviewer=DANA,
        date=TODAY,
        outcome="signed",
        assumptions=[{"question_id": review.question.id, "words": "Treat the services as listed."}],
    ).to_json()
    run.status = "signed"


def test_the_picture_of_a_finished_brief_opens_its_sources_on_the_record(map_runs):
    finished(map_runs)
    client = make_client(map_runs)
    page = client.get(f"{RUN}/facts")
    found = {c["number"]: c for c in cells(page.text)}
    assert list(found) == NUMBERS
    assert "/signed?" in found["7.2"]["href"] and "/signed?" in found["6.1"]["href"]
    record = client.get(found["7.2"]["href"].split("#")[0])
    assert "<mark>" in record.text and "decision-form" not in record.text
    nothing = client.get(found["6.1"]["href"].split("#")[0])
    assert NO_FACT in text_of(nothing.text) and "<mark>" not in nothing.text


def test_a_run_whose_state_holds_no_accounting_draws_no_picture():
    review = section_seven_review()
    review.state.pop("accounting")
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=review)
    page = make_client(runs).get(f"{RUN}/review")
    assert page.status_code == 200 and 'data-hook="map"' not in page.text
