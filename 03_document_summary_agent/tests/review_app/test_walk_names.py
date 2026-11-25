"""Firm and provider facts read in words: their names, their rows as field and value, no codes."""

from __future__ import annotations

import re

import pytest
from review_fakes import FakeRuns
from review_fixtures import make_client
from review_helpers import RUN, decide, text_of
from review_table_fakes import tables_review

CODES = re.compile(r"FIRM-0|PROVIDER-0|\bnull\b|\brow:", re.IGNORECASE)


@pytest.fixture()
def table_runs() -> FakeRuns:
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=tables_review())
    return runs


def cited(runs):
    return [c for s in runs._runs["run-1"].review.request.statements for c in s.facts]


def test_a_firm_or_provider_fact_is_named_in_words_wherever_it_is_listed(table_runs):
    client = make_client(table_runs)
    text = text_of(client.get(f"{RUN}/review").text)
    assert "Paragraph 7.1, obligation" in text and "Firm profile" in text
    profile = text_of(client.get(f"{RUN}/review?tab=profile").text)
    for name in (
        "Harbour Mutual Bank, firm profile",
        "Total assets",
        "Operational resilience senior manager",
        "Provider NimbusCloud, contract ends",
        "NimbusCloud, provider",
        "PayCore Ltd, provider",
    ):
        assert name in profile, name
    facts_page = text_of(make_client(table_runs).get(f"{RUN}/facts").text)
    assert "Harbour Mutual Bank, firm profile: total assets" in facts_page
    assert "PayCore Ltd, provider: service" in facts_page


def _row_table(page):
    found = re.search(r'<table class="data row-table".*?</table>', page.text, flags=re.S)
    assert found, "the source of a table row has no field and value table"
    return found.group(0)


def test_the_source_of_a_table_row_opens_as_a_table_of_field_and_value_in_words(table_runs):
    client = make_client(table_runs)
    manager = next(
        c for c in cited(table_runs) if c.fact.attributes.get("field", "").startswith("operational")
    )
    page = client.get(f"{RUN}/review", params={"fact": manager.fact.id})
    table = _row_table(page)
    pairs = re.findall(r"<th scope=\"row\">(.*?)</th>\s*<td>(.*?)</td>", table, flags=re.S)
    shown = {text_of(k).strip(): text_of(v).strip() for k, v in pairs}
    assert shown["Name"] == "Harbour Mutual Bank"
    assert shown["Type"] == "retail bank"
    assert shown["Customers"] == "1,200,000"
    assert shown["Total assets"] == "£9 billion"
    assert shown["Operational resilience senior manager"] == "none named"
    assert "NimbusCloud, contract ends 30 June 2027, material" in shown["Providers"]
    assert "PayCore Ltd, contract ends 31 December 2029, material" in shown["Providers"]
    marked = re.findall(r"<mark>(.*?)</mark>", table, flags=re.S)
    assert [text_of(m).strip() for m in marked] == ["none named"]
    assert 'data-hook="paragraph"' not in page.text
    assert '"firm_id"' not in page.text


def test_the_source_of_a_provider_link_marks_that_provider_alone(table_runs):
    link = next(c for c in cited(table_runs) if c.fact.attributes.get("field") == "provider_link")
    page = make_client(table_runs).get(f"{RUN}/review", params={"fact": link.fact.id})
    marked = re.findall(r"<mark>(.*?)</mark>", _row_table(page), flags=re.S)
    assert [text_of(m).strip() for m in marked] == [
        "NimbusCloud, contract ends 30 June 2027, material"
    ]


def test_the_source_of_a_provider_row_is_a_table_too(table_runs):
    service = next(
        c for c in cited(table_runs) if c.fact.attributes.get("value") == "card processing"
    )
    table = _row_table(
        make_client(table_runs).get(f"{RUN}/review", params={"fact": service.fact.id})
    )
    pairs = re.findall(r"<th scope=\"row\">(.*?)</th>\s*<td>(.*?)</td>", table, flags=re.S)
    assert {text_of(k).strip(): text_of(v).strip() for k, v in pairs} == {
        "Name": "PayCore Ltd",
        "Service": "card processing",
    }


def test_a_missing_value_reads_none_named_in_the_fact_fields(table_runs):
    manager = next(
        c for c in cited(table_runs) if c.fact.attributes.get("field", "").startswith("operational")
    )
    page = make_client(table_runs).get(f"{RUN}/review", params={"fact": manager.fact.id})
    fields = re.search(r'<dl class="record">.*?</dl>', page.text, flags=re.S).group(0)
    assert "None stated in the paragraph" not in fields
    assert re.search(r"<dt>Field</dt><dd>operational resilience senior manager</dd>", fields)
    assert re.search(r"<dt>Value</dt><dd>none named</dd>", fields)


def test_a_provider_link_fact_names_the_provider_and_the_contract_in_words(table_runs):
    link = next(c for c in cited(table_runs) if c.fact.attributes.get("field") == "provider_link")
    page = make_client(table_runs).get(f"{RUN}/review", params={"fact": link.fact.id})
    fields = re.search(r'<dl class="record">.*?</dl>', page.text, flags=re.S).group(0)
    assert "<dt>Provider</dt><dd>NimbusCloud</dd>" in fields
    assert "<dt>Contract ends</dt><dd>30 June 2027</dd>" in fields
    assert "<dt>Material</dt><dd>Yes</dd>" in fields


def sign_everything(client, runs):
    review = runs._runs["run-1"].review
    for item in cited(runs):
        decide(client, review, item.fact, reason="Read in the source.")
    return client.post(
        f"{RUN}/sign", data={"brief_digest": review.request.brief_digest, "outcome": "signed"}
    )


def every_page(client, runs):
    """Return the address of every page and export of the run, with each fact's source opened."""
    pages = [f"{RUN}/facts", f"{RUN}/facts.csv"]
    for item in cited(runs):
        for part in ("review", "signed"):
            pages.append(f"{RUN}/{part}?fact={item.fact.id}")
    return pages


def test_no_page_of_a_brief_awaiting_review_holds_a_row_code_or_the_word_null(table_runs):
    client = make_client(table_runs)
    found = {}
    for address in [*every_page(client, table_runs), f"{RUN}/review?tab=signoff"]:
        page = client.get(address, follow_redirects=True)
        assert page.status_code == 200, address
        hit = CODES.search(page.text)
        if hit:
            found[address] = hit.group(0)
    assert found == {}


def test_no_page_of_a_signed_brief_holds_a_row_code_or_the_word_null(table_runs):
    client = make_client(table_runs)
    assert sign_everything(client, table_runs).status_code == 303
    found = {}
    for address in [*every_page(client, table_runs), f"{RUN}/signed", f"{RUN}/decisions.csv"]:
        page = client.get(address, follow_redirects=True)
        assert page.status_code == 200, address
        hit = CODES.search(page.text)
        if hit:
            found[address] = hit.group(0)
    assert found == {}
    decisions = client.get(f"{RUN}/decisions.csv").text
    assert "Harbour Mutual Bank, firm profile: total assets" in decisions


def test_the_scan_for_codes_sees_a_code_in_planted_text():
    for planted in ("Row FIRM-001", "PROVIDER-002", "value: null", '{"field": "x", "v": null}'):
        assert CODES.search(planted), planted
