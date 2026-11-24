"""Tests of reading a document into a source, sections and one unit per paragraph."""

import pytest

from context.errors import DocumentFormatError, DocumentNotFoundError
from context.reader import parse_paragraphs, read_document
from fsi_common.ids import digest_bytes, digest_text
from utils.db import DATA_DIR

PS26_4 = DATA_DIR / "documents" / "PS26-4.md"


def test_read_document_gives_ten_sections_and_forty_eight_units():
    document = read_document("PS26-4")
    assert len(document.sections) == 10
    assert sum(len(section.paragraphs) for section in document.sections) == 48
    assert len(document.units) == 48
    assert len(document.unit_text) == 48


def test_read_document_source_digest_is_the_digest_of_the_file_bytes():
    document = read_document("PS26-4")
    assert document.source.digest == digest_bytes(PS26_4.read_bytes())
    assert document.source.key == "PS26-4"
    assert document.source.kind == "document"
    assert document.source.title.startswith("Policy Statement PS26/4")
    assert document.source.locator == "03_document_summary_agent/data/documents/PS26-4.md"


def test_read_document_unit_text_is_the_paragraph_without_its_number():
    document = read_document("PS26-4")
    paragraph = document.paragraph("para:7.1")
    assert paragraph is not None
    assert paragraph.text.startswith("Firms must submit an initial notification to the FSOA")
    assert not paragraph.text.startswith("7.1")
    unit = next(unit for unit in document.units if unit.anchor == "para:7.1")
    assert unit.text_digest == digest_text(paragraph.text)
    assert document.unit_text[unit.id] == paragraph.text
    assert unit.source_id == document.source.id


def test_read_document_groups_paragraphs_by_section_as_the_starter_splits_them():
    document = read_document("PS26-4")
    section7 = next(section for section in document.sections if section.number == "7")
    assert section7.title == "Incident reporting"
    assert [p.number for p in section7.paragraphs] == ["7.1", "7.2", "7.3", "7.4", "7.5"]
    assert section7.text.startswith("7.1 Firms must submit")
    assert [s.number for s in document.sections] == [str(n) for n in range(1, 11)]


def test_read_document_twice_gives_identical_records():
    first, second = read_document("PS26-4"), read_document("PS26-4")
    assert first.source.to_json() == second.source.to_json()
    assert [u.to_json() for u in first.units] == [u.to_json() for u in second.units]
    assert first.unit_text == second.unit_text


def test_read_document_unknown_document_is_named():
    with pytest.raises(DocumentNotFoundError, match="PS99-9"):
        read_document("PS99-9")


def test_parse_paragraphs_keeps_every_block_in_order():
    text = "7.1 First paragraph.\n\n7.2 Second paragraph\nwraps onto a second line.\n\n7.3 Third."
    paragraphs = parse_paragraphs("7", text)
    assert [p.number for p in paragraphs] == ["7.1", "7.2", "7.3"]
    assert paragraphs[1].text == "Second paragraph\nwraps onto a second line."
    assert paragraphs[0].anchor == "para:7.1"


def test_parse_paragraphs_refuses_a_block_that_is_not_a_numbered_paragraph():
    with pytest.raises(DocumentFormatError, match="section 7.*Stray note"):
        parse_paragraphs("7", "7.1 First.\n\nStray note with no number.")


def test_parse_paragraphs_refuses_a_paragraph_numbered_for_another_section():
    with pytest.raises(DocumentFormatError, match="8.1.*section 7"):
        parse_paragraphs("7", "7.1 First.\n\n8.1 Belongs elsewhere.")


def test_parse_paragraphs_refuses_a_repeated_number():
    with pytest.raises(DocumentFormatError, match="7.1.*twice"):
        parse_paragraphs("7", "7.1 First.\n\n7.1 Again.")


def test_parse_paragraphs_refuses_a_section_with_no_paragraph():
    with pytest.raises(DocumentFormatError, match="Section 7 holds no paragraph"):
        parse_paragraphs("7", "")
