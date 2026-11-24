"""A fact holds a list of requirements; every page and export shows each one, in order."""

from __future__ import annotations

import csv
import io
import re

from review_fakes import FakeRuns, section_seven_review
from review_fixtures import make_client
from review_helpers import RUN, signed_section_seven_run, text_of

from review_app.source_view import attribute_rows, attribute_value

FIRST = "Notify the regulator of a major incident"
SECOND = "Notify the regulator within 24 hours of detection"
BOTH = f"(1) {FIRST}; (2) {SECOND}"


def _two_requirement_fact(review):
    fact = review.request.statements[0].facts[0].fact
    assert fact.attributes["requirement"] == [FIRST, SECOND]
    return fact


def test_the_review_page_shows_each_requirement_of_the_open_fact_in_order():
    runs = FakeRuns()
    review = section_seven_review()
    runs.add("run-1", "awaiting_review", review=review)
    fact = _two_requirement_fact(review)
    page = make_client(runs).get(f"{RUN}/review", params={"fact": fact.id})
    assert BOTH in text_of(page.text)


def test_the_facts_table_and_its_export_hold_each_requirement_in_order():
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=section_seven_review())
    c = make_client(runs)
    page = c.get(f"{RUN}/facts")
    assert BOTH in text_of(page.text)
    rows = list(csv.reader(io.StringIO(c.get(f"{RUN}/facts.csv").text)))
    cell = rows[1][rows[0].index("Requirement")]
    assert cell == BOTH


def test_the_signed_page_facts_page_and_exports_show_each_requirement_in_order():
    c = make_client(signed_section_seven_run())
    signed = c.get(f"{RUN}/signed")
    assert BOTH in text_of(signed.text)
    for path in ("decisions.csv", "facts.csv"):
        rows = list(csv.reader(io.StringIO(c.get(f"{RUN}/{path}").text)))
        header = rows[0]
        cells = [r[header.index("Requirement")] for r in rows[1:]]
        assert any(FIRST in x and SECOND in x for x in cells), path
        assert BOTH in cells, path
    assert BOTH in text_of(c.get(f"{RUN}/facts").text)


def test_every_requirement_of_every_obligation_is_on_the_signed_page():
    review = section_seven_review()
    c = make_client(signed_section_seven_run())
    text = text_of(c.get(f"{RUN}/signed").text)
    for statement in review.request.statements:
        for cited in statement.facts:
            for requirement in cited.fact.attributes["requirement"]:
                assert requirement in text, requirement
    assert len(re.findall(r"<tr>", c.get(f"{RUN}/signed").text)) == 6


def test_a_list_of_requirements_is_written_in_order_and_one_requirement_is_written_alone():
    from review_app.source_view import requirements_text

    assert requirements_text([FIRST, SECOND]) == f"(1) {FIRST}; (2) {SECOND}"
    assert requirements_text([FIRST]) == FIRST
    assert requirements_text(FIRST) == FIRST
    assert requirements_text([]) == "None stated in the paragraph"
    assert requirements_text(None) == "None stated in the paragraph"


def test_the_attribute_list_of_a_fact_writes_its_requirements_the_same_way():
    fact = _two_requirement_fact(section_seven_review())
    assert dict(attribute_rows(fact))["Requirement"] == f"(1) {FIRST}; (2) {SECOND}"
    assert attribute_value(["7.1", "7.2"]) == "7.1, 7.2"


def test_a_fact_about_a_table_row_reads_does_not_apply_for_requirement_and_deadline():
    from review_app.routes_facts import fact_cells

    review = section_seven_review()
    paragraph = next(iter(review.facts.values()))
    row = paragraph.model_copy(
        update={
            "subject": paragraph.subject.model_copy(update={"anchor": "row:FIRM-001"}),
            "kind": "firm_attribute",
            "attributes": {"name": "Harbour Mutual Bank"},
        }
    )
    cells = fact_cells(row, "Awaiting a decision", "normal", None)
    assert cells["requirement"].text == "Does not apply"
    assert cells["deadline"].text == "Does not apply"
    kept = fact_cells(paragraph, "Awaiting a decision", "normal", None)
    assert kept["requirement"].text != "Does not apply"
