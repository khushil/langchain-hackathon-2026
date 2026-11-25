"""The three regulations as the publishers serve them: counts, closure and planted faults.

DORA and the AI Act are held in the repository and are always read. The supervisory statement is
not held: its tests read the cached bytes, which ``regulations-check`` (or ``python -m
context.regulations fetch``) puts in place and checks against the manifest's digest. Under the
gate, ``REQUIRE_REGULATIONS`` makes a missing cache a failure; run alone, the tests skip and name
the reason. ``python -m context.regulations check`` fails whenever a text is absent, its digest
differs or a unit does not close.
"""

from __future__ import annotations

import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter

import pytest

from context.regulations.accounting import account_for_regulation, load_pin, pin_record
from context.regulations.errors import (
    DigestMismatchError,
    RegulationAccountingError,
    RegulationFormatError,
)
from context.regulations.fetch import check_digest, resolve_cache_dir
from context.regulations.manifest import REGULATIONS_DIR, load_manifest
from context.regulations.official_journal import NS, read_official_journal
from context.regulations.readers import read_entry
from context.regulations.supervisory_statement import (
    layout_from_pdf,
    read_supervisory_statement,
)

MANIFEST = load_manifest()


def cached(key: str) -> bytes:
    entry = MANIFEST.get(key)
    path = (
        REGULATIONS_DIR / entry.text_file
        if entry.text_file
        else resolve_cache_dir() / entry.cache_file
    )
    if not path.exists():
        message = f"{key} is not cached; run python -m context.regulations fetch"
        if os.environ.get("REQUIRE_REGULATIONS"):
            pytest.fail(message)  # the gate sets this, so a missing text is a failure there
        pytest.skip(message)
    data = path.read_bytes()
    check_digest(entry, data, where="cached")
    return data


@pytest.fixture(scope="module")
def dora():
    return read_entry(MANIFEST.get("DORA"), cached("DORA"))


@pytest.fixture(scope="module")
def ai_act():
    return read_entry(MANIFEST.get("AI-ACT"), cached("AI-ACT"))


@pytest.fixture(scope="module")
def ss():
    return read_entry(MANIFEST.get("SS1-23"), cached("SS1-23"))


def test_dora_reads_into_the_structure_the_act_publishes(dora):
    assert dora.structure_counts() == {"title": 1, "chapter": 9, "section": 6, "article": 64}
    kinds = dora.unit_counts()
    assert kinds["recital"] == 106
    assert kinds["citation"] == 6
    assert kinds["footnote"] == 39
    assert len(dora.items) == 501


def test_the_ai_act_reads_into_the_structure_the_act_publishes(ai_act):
    counts = ai_act.structure_counts()
    assert (counts["chapter"], counts["article"], counts["annex"]) == (13, 113, 13)
    assert counts["section"] == 16
    kinds = ai_act.unit_counts()
    assert kinds["recital"] == 180
    assert kinds["citation"] == 7
    assert kinds["footnote"] == 58
    assert len(ai_act.items) == 930


def test_the_statement_reads_into_five_principles_and_twenty_three_sub_principles(ss):
    counts = ss.structure_counts()
    assert (counts["chapter"], counts["principle"], counts["subprinciple"]) == (4, 5, 23)
    kinds = ss.unit_counts()
    assert kinds["paragraph"] == 9 + 15 + 8
    assert kinds["principle_overview"] == kinds["principle_statement"] == 5
    assert kinds["footnote"] == 23
    assert kinds["principle_point"] == 82
    assert len(ss.items) == 154


@pytest.mark.parametrize("fixture", ["dora", "ai_act", "ss"])
def test_every_unit_closes_against_the_pin_and_every_element_is_claimed(fixture, request):
    read = request.getfixturevalue(fixture)
    outcome = account_for_regulation(read, load_pin(read.source.key))
    assert outcome.units_read == outcome.units_pinned == len(read.items)
    assert read.closure.elements_total == read.closure.elements_claimed
    assert outcome.line.endswith("units read and accounted for")


@pytest.mark.parametrize("fixture", ["dora", "ai_act", "ss"])
def test_no_unit_is_empty_and_every_anchor_is_unique(fixture, request):
    read = request.getfixturevalue(fixture)
    anchors = [u.anchor for u in read.items]
    assert len(anchors) == len(set(anchors))
    assert all(u.text.strip() for u in read.items)
    assert len(read.units) == len(read.items)


def test_irregular_lists_are_listed_not_hidden(dora, ai_act):
    assert dora.closure.irregular_lists == ("art:36/1",)
    assert ai_act.closure.irregular_lists == ("anx:II",)


def test_every_article_and_annex_has_at_least_one_unit(dora, ai_act):
    for read, articles in ((dora, 64), (ai_act, 113)):
        for number in range(1, articles + 1):
            prefix = f"art:{number}"
            assert any(u.anchor == prefix or u.anchor.startswith(prefix + "/") for u in read.items)
    for numeral in (
        "I",
        "II",
        "III",
        "IV",
        "V",
        "VI",
        "VII",
        "VIII",
        "IX",
        "X",
        "XI",
        "XII",
        "XIII",
    ):
        assert any(u.anchor.startswith(f"anx:{numeral}") for u in ai_act.items)


def drop_by_id(data: bytes, identifier: str) -> bytes:
    """Remove the one element with an id from the act, as a faulty reader would lose it."""
    ET.register_namespace("", NS.strip("{}"))
    root = ET.fromstring(data)
    for parent in root.iter():
        for child in list(parent):
            if child.get("id") == identifier:
                parent.remove(child)
                return ET.tostring(root, encoding="utf-8")
    raise AssertionError(f"no element {identifier}")


def read_dora(data: bytes):
    entry = MANIFEST.get("DORA")
    return read_official_journal(
        data, key=entry.key, title=entry.title, locator=entry.address, terms=entry.terms
    )


def test_planted_a_dropped_article_in_the_real_act_is_named():
    with pytest.raises(RegulationFormatError, match="Article 12 is missing"):
        read_dora(drop_by_id(cached("DORA"), "art_12"))


def test_planted_a_dropped_paragraph_in_the_real_act_is_named():
    with pytest.raises(RegulationFormatError, match=r"Paragraph 2 of Article 6 is missing"):
        read_dora(drop_by_id(cached("DORA"), "006.002"))


def test_planted_a_dropped_recital_in_the_real_act_is_named():
    with pytest.raises(RegulationFormatError, match="Recital 40 is missing"):
        read_dora(drop_by_id(cached("DORA"), "rct_40"))


def test_planted_a_paragraph_read_twice_in_the_real_act_is_named():
    data = cached("DORA").decode("utf-8")
    start = data.index('<div id="005.002">')
    end = data.index("</div>", start)
    # A paragraph div holds tables and further divs only when it has points; take a flat one.
    flat = re.search(r'<div id="005\.002">(?:(?!<div).)*?</div>', data, re.DOTALL)
    assert flat is not None and start < end
    doubled = data.replace(flat.group(0), flat.group(0) * 2, 1)
    with pytest.raises(RegulationFormatError, match=r"art:5/2.*twice"):
        read_dora(doubled.encode("utf-8"))


def test_planted_one_changed_byte_is_a_digest_mismatch_naming_both_digests():
    entry = MANIFEST.get("DORA")
    data = bytearray(cached("DORA"))
    data[1000] ^= 0x01
    with pytest.raises(DigestMismatchError, match=entry.digest):
        check_digest(entry, bytes(data), where="fetched")


def test_planted_a_unit_missing_from_the_real_reading_is_named(dora):
    import dataclasses

    faulty = dataclasses.replace(dora, items=tuple(i for i in dora.items if i.anchor != "art:28/8"))
    with pytest.raises(RegulationAccountingError, match=r"art:28/8") as caught:
        account_for_regulation(faulty, pin_record(dora))
    assert caught.value.missing == ["art:28/8"]


def test_planted_a_dropped_paragraph_in_the_real_statement_is_named():
    pdf = cached("SS1-23")
    layout = layout_from_pdf(pdf).decode("utf-8")
    ET.register_namespace("", NS.strip("{}"))
    root = ET.fromstring(layout.encode("utf-8"))
    removed = 0
    for flow in [e for e in root.iter() if e.tag == f"{NS}flow"]:
        for block in [b for b in flow if b.tag == f"{NS}block"]:
            for line in [ln for ln in block if ln.tag == f"{NS}line"]:
                words = [w.text for w in line if w.tag == f"{NS}word"]
                if words[:1] == ["2.7"]:
                    block.remove(line)
                    removed += 1
    assert removed == 1
    entry = MANIFEST.get("SS1-23")
    with pytest.raises(RegulationFormatError, match=r"Paragraph 2\.7 is missing"):
        read_supervisory_statement(
            pdf,
            key=entry.key,
            title=entry.title,
            locator=entry.address,
            terms=entry.terms,
            layout=ET.tostring(root, encoding="utf-8"),
        )


LABEL = re.compile(r"^\(?[A-Za-z0-9]{1,6}\)?\.?$|^[—–-]$")
HEADING_START = ("Article ", "CHAPTER ", "SECTION ", "Section ", "ANNEX ")
FURNITURE_START = ("THE EUROPEAN PARLIAMENT", "Whereas:", "HAVE ADOPTED", "ELI:", "ISSN ")


def source_text(element: ET.Element) -> str:
    """A paragraph's text from the source markup, with footnote references taken out."""
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        if node.tag == f"{NS}a" and any(
            "oj-note-tag" in (c.get("class") or "") for c in node.iter()
        ):
            parts.append(node.tail or "")
            return
        parts.append(node.text or "")
        for child in node:
            walk(child)
        parts.append(node.tail or "")

    node_tail = element.tail
    element.tail = None
    walk(element)
    element.tail = node_tail
    text = unicodedata.normalize("NFC", " ".join("".join(parts).split()))
    return re.sub(r"\s+([,.;:)])", r"\1", text)


@pytest.mark.parametrize("key", ["DORA", "AI-ACT"])
def test_every_source_paragraph_is_found_word_for_word_in_the_units(key):
    """The text is split into units for reading and no wording is altered.

    Every paragraph element of the source is found, word for word, inside the units' text, or is a
    point label, a heading whose words are in the structure, or page furniture of a named kind.
    """
    entry = MANIFEST.get(key)
    data = cached(key)
    read = read_entry(entry, data)
    blob = " ".join(unicodedata.normalize("NFC", u.text) for u in read.items)
    titles = " ".join(n.title for n in read.structure)
    root = ET.fromstring(data)
    parents = {c: p for p in root.iter() for c in p}
    tally = {"in units": 0, "label": 0, "heading": 0, "furniture": 0}
    missing: list[str] = []
    for p in root.iter(f"{NS}p"):
        text = source_text(p)
        if not text:
            continue
        classes = p.get("class") or ""
        if any(c in classes for c in ("oj-hd-", "oj-signatory")) or text.startswith(
            FURNITURE_START
        ):
            tally["furniture"] += 1
        elif LABEL.match(text):
            tally["label"] += 1
        elif text in blob or re.sub(r"^(\d+\.|\(\d+\))\s+", "", text) in blob:
            tally["in units"] += 1
        elif (
            text.startswith(HEADING_START)
            or text in titles
            or "oj-ti-" in classes
            or "oj-doc-ti" in classes
        ):
            tally["heading"] += 1
        elif parents.get(p) is not None and "eli-title" in (parents[p].get("class") or ""):
            tally["heading"] += 1
        else:
            missing.append(text[:70])
    assert missing == []
    assert sum(tally.values()) == len([p for p in root.iter(f"{NS}p") if source_text(p)])
    assert tally["in units"] > 1000


def test_a_missing_statement_fails_when_the_gate_requires_it_and_skips_otherwise(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("REGULATIONS_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("REQUIRE_REGULATIONS", "1")
    with pytest.raises(pytest.fail.Exception, match="not cached"):
        cached("SS1-23")
    monkeypatch.delenv("REQUIRE_REGULATIONS")
    with pytest.raises(pytest.skip.Exception, match="not cached"):
        cached("SS1-23")


def unit_text_problems(read, data: bytes) -> tuple[list[str], list[str]]:
    """Compare each unit's text with the join of the source paragraphs it claims.

    Returns:
        The units that lost or gained wording, and the units compared by letters only.
    """
    root = ET.fromstring(data)
    paragraphs = list(root.iter(f"{NS}p"))
    parents = {c: p for p in root.iter() for c in p}

    def inside_paragraph(element):
        while element is not None:
            if element.tag == f"{NS}p":
                return True
            element = parents.get(element)
        return False

    outside = Counter()
    for element in root.iter():
        if inside_paragraph(element):
            continue
        outside.update((element.text or "").split())
        for child in element:
            outside.update((child.tail or "").split())

    def letters(text: str) -> Counter:
        return Counter(c for c in re.sub(r"^(\d+\.|\(\d+\))\s+", "", text) if not c.isspace())

    outside_letters = letters(" ".join(outside.elements()))
    problems: list[str] = []
    by_letters: list[str] = []
    for unit in read.items:
        if not unit.paragraph_indexes:
            continue
        joined = " ".join(source_text(paragraphs[i]) for i in unit.paragraph_indexes)
        joined = re.sub(r"^(\d+\.|\(\d+\))\s+", "", joined)
        if " ".join(unit.text.split()) == " ".join(joined.split()):
            continue
        # The markup keeps some citations in spans outside any paragraph element, and the words
        # run across element boundaries, so these few units are compared by their letters: nothing
        # of the claimed paragraphs may be lost, and anything added must be among that outside text.
        by_letters.append(unit.anchor)
        mine, theirs = letters(unit.text), letters(joined)
        if theirs - mine:
            problems.append(f"{unit.anchor} lost text")
        if (mine - theirs) - outside_letters:
            problems.append(f"{unit.anchor} gained text")
    return problems, by_letters


@pytest.mark.parametrize(("key", "by_letters"), [("DORA", 0), ("AI-ACT", 10)])
def test_each_units_text_is_the_join_of_the_source_paragraphs_it_claims(key, by_letters):
    """A reader that adds words to a unit is caught, not only one that loses words."""
    data = cached(key)
    problems, compared = unit_text_problems(read_entry(MANIFEST.get(key), data), data)
    assert problems == []
    assert len(compared) <= by_letters, compared


def test_planted_a_reader_that_adds_three_words_to_one_unit_is_caught():
    import dataclasses

    data = cached("DORA")
    read = read_entry(MANIFEST.get("DORA"), data)
    items = tuple(
        dataclasses.replace(i, text=i.text + " and nothing else") if i.anchor == "art:5/2" else i
        for i in read.items
    )
    problems, _ = unit_text_problems(dataclasses.replace(read, items=items), data)
    assert problems == ["art:5/2 gained text"]


def test_planted_a_reader_that_drops_a_word_from_one_unit_is_caught():
    import dataclasses

    data = cached("DORA")
    read = read_entry(MANIFEST.get("DORA"), data)
    items = tuple(
        dataclasses.replace(i, text=i.text.replace("shall", "", 1)) if i.anchor == "art:5/2" else i
        for i in read.items
    )
    problems, _ = unit_text_problems(dataclasses.replace(read, items=items), data)
    assert problems == ["art:5/2 lost text"]
