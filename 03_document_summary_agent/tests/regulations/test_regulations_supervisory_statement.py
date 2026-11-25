"""The supervisory statement reader turns a PDF's word positions into units whose counts close."""

from __future__ import annotations

import pytest
from regulation_fixtures import STATEMENT_ANCHORS, sample_statement

from context.regulations.errors import RegulationFormatError, RegulationToolMissingError
from context.regulations.supervisory_statement import (
    layout_from_pdf,
    read_supervisory_statement,
)

PDF = b"%PDF-1.7 stands in for the real file; the layout is given beside it"


def read(layout: bytes | None = None, **kwargs):
    return read_supervisory_statement(
        PDF,
        key="SS-SAMPLE",
        title="Sample statement",
        locator="https://example.org/ss.pdf",
        terms="Not republished.",
        layout=layout if layout is not None else sample_statement(**kwargs),
    )


def test_units_follow_the_statement_in_order_with_their_anchors():
    assert [u.anchor for u in read().items] == [*STATEMENT_ANCHORS]


def test_a_paragraph_holds_its_text_without_number_footnote_marker_or_running_head():
    result = read()
    assert result.text("para:1.1") == "This statement sets out expectations for banks’ sample risk."
    assert result.text("para:1.3") == "The policy applies from 1 January 2099."
    assert result.unit("para:1.1").note_numbers == (1,)
    assert "Prudential" not in " ".join(result.unit_text.values())
    assert "Page " not in " ".join(result.unit_text.values())


def test_a_list_inside_a_paragraph_stays_inline_and_a_hyphenated_break_is_joined():
    result = read()
    assert result.text("para:2.1") == (
        "Firms use models in several ways: i. to price products; and ii. to measure risk."
    )
    assert "re-performed where relevant." in result.text("prin:1.1/b")


def test_a_lettered_point_of_a_sub_principle_is_its_own_unit_with_roman_points_inline():
    result = read()
    assert result.text("prin:1.1/a") == (
        "Firms should adopt the following definition of a model: (i) a quantitative method; and "
        "(ii) an output of estimates."
    )
    assert result.text("prin:1.1") == "A formal definition sets the scope of the framework."
    assert "prin:1.2" not in [u.anchor for u in read().items]


def test_a_label_the_layout_reports_as_its_own_line_on_the_same_row_is_joined_to_its_text():
    result = read()
    assert result.text("prin:2.1/c") == "The board should review the framework."
    assert "c)" not in result.text("prin:2.1/b")


def test_the_principle_statement_is_read_in_the_overview_and_again_in_the_principles():
    result = read()
    assert result.text("ovw:1") == result.text("prin:1") == "Firms should keep a model inventory."
    assert result.unit("ovw:2").label == "Principle 2, overview"
    assert result.unit("prin:1.1/b").label == "Principle 1.1(b)"
    assert result.unit("para:1.2").label == "Paragraph 1.2"


def test_footnotes_are_units_and_their_markers_are_matched():
    result = read()
    assert result.text("note:1") == "The term banks includes building societies."
    assert result.text("note:2") == "A model includes expert judgement."


def test_structure_is_counted_and_titled_with_markers_removed():
    result = read()
    assert result.structure_counts() == {
        "chapter": 4,
        "topic": 1,
        "principle": 2,
        "subprinciple": 3,
    }
    assert result.node("chapter:4").title == "Principles for banks"
    assert result.node("subprinciple:1.1").title == "Model definition"
    assert result.node("subprinciple:1.1").parent == "principle:1"
    assert result.unit("prin:2.1/a").parents == ("chapter:4", "principle:2", "subprinciple:2.1")


def test_every_line_is_claimed_once_and_the_closure_says_so():
    closure = read().closure
    assert closure.elements_total == closure.elements_claimed
    assert closure.unit_total == len(STATEMENT_ANCHORS)
    assert closure.furniture["cover page"] == 3
    assert closure.furniture["running head"] == 4
    assert closure.furniture["page number"] == 4


def test_reading_twice_gives_identical_records():
    first, second = read(), read()
    assert first.units == second.units
    assert first.unit_text == second.unit_text


def test_the_source_digest_is_that_of_the_pdf_bytes():
    assert read().source.digest.startswith("sha256:")
    assert read().source.kind == "supervisory_statement"


def test_a_dropped_paragraph_is_a_gap_and_is_named():
    with pytest.raises(RegulationFormatError, match=r"Paragraph 1\.2 is missing"):
        read(drop=["1.2 It applies"])


def test_a_dropped_lettered_point_is_a_gap_and_is_named():
    drop = ["b) Where methods", "consider the framework", "performed where"]
    with pytest.raises(RegulationFormatError, match=r"Point \(b\) of Principle 1\.1 is missing"):
        read(drop=drop)


def test_a_paragraph_written_twice_is_refused_and_named():
    with pytest.raises(RegulationFormatError, match=r"para:2\.1.*twice"):
        read(repeat=["2.1 Firms use models"])


def test_a_dropped_footnote_leaves_a_marker_with_no_note_and_is_named():
    with pytest.raises(RegulationFormatError, match=r"[Ff]ootnote marker.*2"):
        read(drop=["note:2"])


def test_a_line_that_belongs_to_no_unit_is_refused_not_dropped():
    layout = sample_statement(drop=["2.1 Firms use models"])
    with pytest.raises(RegulationFormatError, match=r"not (claimed|part of)"):
        read(layout)


def test_text_that_is_not_a_layout_is_refused_with_its_reason():
    with pytest.raises(RegulationFormatError, match="not well-formed"):
        read(b"<html><body>unclosed")


def test_a_missing_layout_program_is_reported_with_what_to_install(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(RegulationToolMissingError, match="pdftotext"):
        layout_from_pdf(PDF)
