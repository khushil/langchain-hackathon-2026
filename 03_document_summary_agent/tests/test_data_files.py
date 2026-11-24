"""Tests that the shared examples describe the topic's real data files, digest for digest."""

from fsi_common.examples.data import (
    FIRM_001_ROW,
    PARA_7_1,
    PARA_9_3,
    PROVIDER_002_ROW,
    build_examples,
)
from fsi_common.ids import digest_bytes, digest_text
from utils import PROJECT_ROOT

DATA = PROJECT_ROOT / "data"


def test_the_document_has_10_sections_and_48_paragraphs():
    text = (DATA / "documents" / "PS26-4.md").read_text(encoding="utf-8")
    sections = [line for line in text.splitlines() if line.startswith("## ")]
    paragraphs = [
        line for line in text.splitlines() if line[:1].isdigit() and "." in line.split(" ", 1)[0]
    ]
    assert len(sections) == 10
    assert len(paragraphs) == 48


def test_source_digests_are_the_files_digests():
    ex = build_examples()
    assert ex.document.digest == digest_bytes((DATA / "documents" / "PS26-4.md").read_bytes())
    assert ex.firms.digest == digest_bytes((DATA / "firms.jsonl").read_bytes())
    assert ex.providers.digest == digest_bytes((DATA / "third_party_providers.jsonl").read_bytes())


def test_unit_texts_are_lines_of_the_files():
    document = (DATA / "documents" / "PS26-4.md").read_text(encoding="utf-8").splitlines()
    assert PARA_7_1 in document
    assert PARA_9_3 in document
    assert FIRM_001_ROW in (DATA / "firms.jsonl").read_text(encoding="utf-8").splitlines()
    assert (
        PROVIDER_002_ROW
        in (DATA / "third_party_providers.jsonl").read_text(encoding="utf-8").splitlines()
    )


def test_unit_digests_are_of_those_lines():
    ex = build_examples()
    assert ex.unit_7_1.text_digest == digest_text(PARA_7_1)
    assert ex.unit_firm.text_digest == digest_text(FIRM_001_ROW)


def test_every_quote_is_in_its_unit_text():
    ex = build_examples()
    texts = {
        "para:7.1": PARA_7_1,
        "para:9.3": PARA_9_3,
        "row:FIRM-001": FIRM_001_ROW,
        "row:PROVIDER-002": PROVIDER_002_ROW,
    }
    for fact in (ex.fact_7_1, ex.fact_9_3, ex.fact_notes, ex.fact_service, ex.fact_small_firm):
        assert fact.quote in texts[fact.subject.anchor], fact.id
    assert ex.fact_7_1.attributes["deadline"] in PARA_7_1
    assert ex.fact_9_3.attributes["deadline"] in PARA_9_3
