"""The Official Journal reader turns an act into units whose counts close."""

from __future__ import annotations

import pytest
from regulation_fixtures import ACT_ANCHORS, compose_act

from context.regulations.errors import RegulationFormatError
from context.regulations.official_journal import read_official_journal

LOCATOR = "https://example.org/act"
TERMS = "Test terms: nothing is republished."


def read(data: bytes):
    return read_official_journal(
        data, key="SAMPLE", title="Sample Regulation", locator=LOCATOR, terms=TERMS
    )


def test_units_follow_the_act_in_order_with_their_anchors():
    result = read(compose_act())
    assert [u.anchor for u in result.items] == ACT_ANCHORS


def test_a_unit_holds_its_text_without_its_number_and_with_its_points_inline():
    result = read(compose_act())
    text = result.text("art:1/1")
    assert text.startswith("This Regulation lays down rules on:")
    assert "(a) sample risk management;" in text
    assert "(b) incident reporting, including: (i) major incidents; (ii) minor incidents." in text
    assert result.text("rct:1") == "Operators need clear rules about sample risk."


def test_a_footnote_marker_is_not_part_of_the_text_and_the_note_is_its_own_unit():
    result = read(compose_act())
    assert result.text("art:4/1") == "Operators shall keep records for five years."
    assert result.text("note:1") == "OJ L 1, 1.1.2099, p. 1."
    assert result.unit("art:4/1").note_numbers == (1,)


def test_a_paragraph_less_article_with_numbered_points_gives_a_lead_and_one_unit_per_point():
    result = read(compose_act())
    assert result.text("art:2/lead").startswith("For the purposes of this Regulation")
    assert result.text("art:2/pt2") == "‘incident’ means an event that harms the service;"
    assert result.unit("art:3").label == "Article 3"


def test_labels_name_the_provision_as_a_lawyer_cites_it():
    result = read(compose_act())
    assert result.unit("art:1/2").label == "Article 1(2)"
    assert result.unit("art:2/pt3").label == "Article 2, point (3)"
    assert result.unit("rct:3").label == "Recital 3"
    assert result.unit("anx:II/s2/1").label == "Annex II, Section B, point 1"
    assert result.unit("anx:I/lead").label == "Annex I"


def test_points_of_a_unit_are_listed_by_label_at_the_top_level():
    result = read(compose_act())
    assert result.unit("art:1/1").points == ("(a)", "(b)")
    assert result.unit("anx:I/2").points == ("(a)", "(b)")
    assert result.unit("art:1/2").points == ()


def test_structure_is_counted_by_kind_with_titles_and_parents():
    result = read(compose_act())
    assert result.structure_counts() == {
        "title": 1,
        "chapter": 2,
        "section": 1,
        "article": 4,
        "annex": 2,
        "group": 2,
    }
    article = result.node("article:4")
    assert article.title == "Records"
    assert article.parent == "section:II.1"
    assert result.node("section:II.1").parent == "chapter:II"
    assert result.node("chapter:I").title == "General provisions"
    assert result.node("annex:II").title == "Grouped list"
    assert result.unit("art:4/2").parents == ("chapter:II", "section:II.1", "article:4")


def test_every_paragraph_element_is_claimed_once_and_the_closure_says_so():
    result = read(compose_act())
    closure = result.closure
    assert closure.elements_total == closure.elements_claimed
    assert closure.elements_claimed > len(ACT_ANCHORS)
    assert closure.unit_total == len(ACT_ANCHORS)
    assert "of" in closure.line and str(len(ACT_ANCHORS)) in closure.line


def test_reading_twice_gives_identical_records():
    first = read(compose_act())
    second = read(compose_act())
    assert first.source == second.source
    assert first.units == second.units
    assert first.unit_text == second.unit_text


def test_the_source_records_the_digest_of_the_bytes_and_where_they_came_from():
    data = compose_act()
    result = read(data)
    assert result.source.digest.startswith("sha256:")
    assert result.source.locator == LOCATOR
    assert result.source.kind == "regulation"
    assert read(compose_act(skip={"cit_2"})).source.id != result.source.id


def test_a_dropped_article_is_a_gap_in_the_numbering_and_is_named():
    drop = {"art_3.open", "art_3.body", "art_3.close"}
    with pytest.raises(RegulationFormatError, match=r"Article 3 is missing"):
        read(compose_act(skip=drop))


def test_a_dropped_paragraph_is_a_gap_and_is_named():
    with pytest.raises(RegulationFormatError, match=r"(?i)paragraph 1 of Article 4 is missing"):
        read(compose_act(skip={"art_4.001"}))


def test_a_dropped_recital_is_a_gap_and_is_named():
    with pytest.raises(RegulationFormatError, match=r"Recital 2 is missing"):
        read(compose_act(skip={"rct_2"}))


def test_a_dropped_point_of_a_definitions_article_is_a_gap_and_is_named():
    with pytest.raises(RegulationFormatError, match=r"(?i)point \(2\) of Article 2 is missing"):
        read(compose_act(skip={"art_2.pt2"}))


def test_a_dropped_annex_item_is_a_gap_and_is_named():
    with pytest.raises(RegulationFormatError, match=r"(?i)point 1 of Annex I is missing"):
        read(compose_act(skip={"anx_I.1"}))


def test_a_unit_written_twice_is_refused_and_named():
    with pytest.raises(RegulationFormatError, match=r"art:1/2.*twice|twice.*art:1/2"):
        read(compose_act(repeat={"art_1.002"}))


def test_a_paragraph_the_reader_does_not_know_how_to_place_is_refused_not_dropped():
    stray = ("stray", '<p class="oj-normal">A stray line outside any subdivision.</p>')
    with pytest.raises(RegulationFormatError, match=r"1 paragraph element.*not claimed"):
        read(compose_act(extra=[stray]))


def test_an_act_with_no_articles_is_refused():
    with pytest.raises(RegulationFormatError, match="no article"):
        read(
            compose_act(
                skip={
                    k
                    for k, _ in __import__("regulation_fixtures").act_parts()
                    if k.startswith("art_")
                }
            )
        )


def test_text_that_is_not_an_act_is_refused_with_its_reason():
    with pytest.raises(RegulationFormatError, match="not well-formed"):
        read(b"<html><body><p>unclosed")


def test_text_that_stands_outside_every_paragraph_and_every_unit_is_refused_not_dropped():
    orphan = ("orphan", '<div class="stray">Text outside a paragraph.</div>')
    with pytest.raises(RegulationFormatError, match=r"text outside.*'Text outside a paragraph"):
        read(compose_act(extra=[orphan]))


def test_text_in_a_span_inside_a_unit_but_outside_a_paragraph_is_kept_in_the_unit():
    data = compose_act().replace(
        b'<td valign="top"><p class="oj-normal">Operators of payment services.</p></td>',
        b'<td valign="top"><span>Operators of payment services.</span></td>',
    )
    assert read(data).text("anx:I/1") == "Operators of payment services."


def test_a_footnote_marker_stands_out_without_brackets_or_a_space_before_the_stop():
    result = read(compose_act())
    assert result.text("art:4/1") == "Operators shall keep records for five years."
    assert "()" not in " ".join(result.unit_text.values())


def test_a_marker_in_an_unnumbered_article_is_recorded_and_its_missing_note_is_named():
    data = compose_act().replace(
        b"This Regulation shall apply from 1 January 2099.",
        b'This Regulation shall apply from 1 January 2099 <a href="#n"><span class="oj-super '
        b'oj-note-tag">2</span></a>.',
    )
    with pytest.raises(RegulationFormatError, match=r"[Ff]ootnote marker.*2.*no footnote"):
        read(data)


def test_a_footnote_that_no_text_marks_is_named():
    extra = ("note_2", '<p class="oj-note">(2) OJ L 2, 1.1.2099, p. 2.</p>')
    with pytest.raises(RegulationFormatError, match=r"Footnote 2 is never marked"):
        read(compose_act(extra=[extra]))
