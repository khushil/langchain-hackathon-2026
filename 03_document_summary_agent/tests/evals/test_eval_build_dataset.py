"""Tests for the dataset builder: its reads, its checks and its determinism."""

import json
from pathlib import Path

import pytest
from evals import build_dataset as bd

from tools.documents import _split_into_sections

TOPIC = Path(__file__).resolve().parents[2]
LABELS = TOPIC / "evals" / "data" / "reference_labels.tsv"
DOCUMENT = TOPIC / "data" / "documents" / "PS26-4.md"


@pytest.fixture(scope="module")
def built():
    return bd.build(LABELS, DOCUMENT)


def test_labels_digest_is_the_one_on_record():
    assert bd.sha256_of(LABELS) == bd.LABELS_SHA256


def test_read_labels_returns_all_77_rows():
    rows = bd.read_labels(LABELS)
    assert len(rows) == 77
    assert sum(r["kind"] == "obligation" for r in rows) == 39
    assert len({r["paragraph"] for r in rows if r["kind"] == "obligation"}) == 23


def test_read_labels_refuses_a_wrong_header(tmp_path):
    bad = tmp_path / "labels.tsv"
    bad.write_text("paragraph\tsection\n1.1\t1\n", encoding="utf-8")
    with pytest.raises(bd.LabelFormatError, match="header"):
        bd.read_labels(bad)


def test_read_labels_refuses_a_short_row(tmp_path):
    lines = LABELS.read_text(encoding="utf-8").splitlines()
    bad = tmp_path / "labels.tsv"
    bad.write_text("\n".join([lines[0], "1.1\t1\t1\tcontext"]), encoding="utf-8")
    with pytest.raises(bd.LabelFormatError, match="row 2"):
        bd.read_labels(bad)


def test_the_real_labels_pass_every_check(built):
    assert built.problems == []


def test_sections_file_has_ten_lines_in_section_order(built):
    lines = built.sections.splitlines()
    assert len(lines) == 10
    assert [json.loads(line)["key"] for line in lines] == [
        f"PS26-4/section/{n}" for n in range(1, 11)
    ]


def test_documents_file_has_one_line_with_every_item_and_paragraph(built):
    lines = built.documents.splitlines()
    assert len(lines) == 1
    example = json.loads(lines[0])
    assert example["key"] == "PS26-4/FIRM-001"
    assert len(example["reference_outputs"]["items"]) == 77
    assert len(example["reference_outputs"]["paragraphs"]) == 48
    assert len(example["reference_outputs"]["paragraph_texts"]) == 48
    assert example["inputs"]["request"]["document_id"] == "PS26-4"
    assert example["inputs"]["request"]["firm_id"] == "FIRM-001"


def test_section_text_is_what_the_starter_splitter_gives(built):
    starter = _split_into_sections(DOCUMENT.read_text(encoding="utf-8"))
    for line, section in zip(built.sections.splitlines(), starter, strict=True):
        got = json.loads(line)["inputs"]["section"]
        assert got == {"number": section.number, "title": section.title, "text": section.text}


def test_item_shape_follows_the_fixture_format(built):
    section7 = json.loads(built.sections.splitlines()[6])
    assert section7["reference_outputs"]["paragraphs"] == ["7.1", "7.2", "7.3", "7.4", "7.5"]
    first = section7["reference_outputs"]["items"][0]
    assert first["paragraph"] == "7.1"
    assert first["item"] == 1
    assert first["kind"] == "obligation"
    assert first["deadline_as_written"].startswith("within 4 hours of classifying")
    assert first["cross_refs"] == []
    assert first["firms"]["FIRM-001"]["applies"] == "applies"
    assert first["conditions"] == "for each major incident"
    no_deadline = section7["reference_outputs"]["items"][3]
    assert (no_deadline["paragraph"], no_deadline["item"]) == ("7.3", 2)
    assert no_deadline["deadline_as_written"] is None


def test_cross_refs_are_split_into_a_list(built):
    document = json.loads(built.documents)
    item = next(i for i in document["reference_outputs"]["items"] if i["paragraph"] == "9.1")
    assert item["cross_refs"] == ["2.3", "4.1", "4.2", "5.1", "6.1"]


def test_metadata_carries_both_digests_and_how_the_labels_were_made(built):
    meta = json.loads(built.sections.splitlines()[0])["metadata"]
    assert meta["labels_sha256"] == "sha256:" + bd.LABELS_SHA256
    assert meta["document_sha256"] == "sha256:" + bd.sha256_of(DOCUMENT)
    assert "two independent labelling agents" in meta["labels_made_by"]
    assert "hand" not in meta["labels_made_by"].lower()


def test_two_builds_give_identical_bytes(built):
    again = bd.build(LABELS, DOCUMENT)
    assert again.sections == built.sections
    assert again.documents == built.documents


def _planted(tmp_path, old, new):
    text = LABELS.read_text(encoding="utf-8")
    assert text.count(old) >= 1
    out = tmp_path / "labels.tsv"
    out.write_text(text.replace(old, new, 1), encoding="utf-8")
    return out


def test_one_changed_evidence_character_is_reported(tmp_path):
    planted = _planted(tmp_path, "intermediate report within 72", "intermediate report within 73")
    problems = bd.build(planted, DOCUMENT).problems
    assert any("not word for word" in p and "7.2" in p for p in problems)
    assert any("digest" in p for p in problems)


def test_a_missing_paragraph_is_reported(tmp_path):
    lines = [
        line
        for line in LABELS.read_text(encoding="utf-8").splitlines()
        if not line.startswith("10.3\t")
    ]
    out = tmp_path / "labels.tsv"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    problems = bd.build(out, DOCUMENT).problems
    assert any("47 of 48 paragraphs" in p and "10.3" in p for p in problems)


def test_an_unknown_kind_is_reported(tmp_path):
    out = _planted(tmp_path, "\tregulator_action\t", "\tregulatory_act\t")
    assert any("kind" in p for p in bd.build(out, DOCUMENT).problems)


def test_an_obligation_without_a_requirement_is_reported(tmp_path):
    out = _planted(tmp_path, "Identify the firm's important business services.", "")
    assert any("requirement" in p for p in bd.build(out, DOCUMENT).problems)


def test_evidence_over_thirty_words_is_reported(tmp_path):
    long_quote = "Firms must identify their important business services by 31 March 2027."
    out = _planted(tmp_path, long_quote, " ".join([long_quote] * 4))
    assert any("30 words" in p for p in bd.build(out, DOCUMENT).problems)


def test_check_passes_on_the_files_on_disk():
    assert bd.main(["--check"]) == 0


def test_check_fails_when_a_file_on_disk_differs(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    built = bd.build(LABELS, DOCUMENT)
    (data / "sections.jsonl").write_text(built.sections, encoding="utf-8")
    (data / "documents.jsonl").write_text(built.documents + " ", encoding="utf-8")
    code = bd.main(["--check", "--out-dir", str(data)])
    assert code == 1
    assert "documents.jsonl" in capsys.readouterr().out


def test_check_fails_when_a_file_is_missing(tmp_path, capsys):
    assert bd.main(["--check", "--out-dir", str(tmp_path)]) == 1
    assert "missing" in capsys.readouterr().out


def test_check_with_planted_labels_exits_one(tmp_path):
    planted = _planted(tmp_path, "intermediate report within 72", "intermediate report within 73")
    assert bd.main(["--check", "--labels", str(planted)]) == 1


def test_build_writes_both_files_and_reports_counts(tmp_path, capsys):
    assert bd.main(["--out-dir", str(tmp_path)]) == 0
    assert len((tmp_path / "sections.jsonl").read_text(encoding="utf-8").splitlines()) == 10
    assert len((tmp_path / "documents.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    out = capsys.readouterr().out
    assert "10 of 10 sections" in out
    assert "48 of 48 paragraphs" in out
