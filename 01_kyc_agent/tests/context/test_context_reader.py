"""The applications and the two lists read whole into sources and units."""

import json

import pytest

from context.errors import ApplicationNotFoundError
from context.reader import (
    SCREENING_SOURCE_KEY,
    entries_of,
    read_applications,
    read_screenings,
    screening_anchor,
)
from fsi_common.ids import digest_bytes
from utils import PROJECT_ROOT, db


def test_every_application_is_a_unit_with_its_own_text():
    read = read_applications()
    rows = db.table("applications")
    assert len(read.units) == len(rows) == 25
    assert [u.anchor for u in read.units] == [f"row:{r['customer_id']}" for r in rows]
    for unit, row in zip(read.units, rows, strict=True):
        assert read.unit_text[unit.id] == row["application"]
    path = PROJECT_ROOT / "data" / "applications.jsonl"
    assert read.source.digest == digest_bytes(path.read_bytes())
    assert read.source.key == "applications"


def test_two_reads_give_identical_records():
    assert read_applications() == read_applications()
    assert read_screenings() == read_screenings()


def test_the_lists_are_read_entry_by_entry_in_file_order():
    entries = entries_of()
    assert [e.anchor_part for e in entries] == [f"sanctions-{n}" for n in range(1, 9)] + [
        f"pep-{n}" for n in range(1, 7)
    ]
    first = entries[0]
    assert (first.list, first.name, first.date_of_birth) == (
        "sanctions",
        "Dmitry Volkonskiy",
        "1975-09-11",
    )
    assert first.detail == "Karvonia arms embargo"
    assert entries[8].date_of_birth is None
    assert entries[8].detail == "Deputy Minister of Finance, Valdoria"
    assert json.loads(entries[8].line)["name"] == "Viktor Harlan"


def test_every_application_meets_every_entry_once():
    read = read_screenings()
    assert len(read.units) == 25 * 14 == 350
    anchors = [u.anchor for u in read.units]
    assert len(set(anchors)) == 350
    assert screening_anchor("CUST-003", "sanctions-1") in anchors
    assert read.source.key == SCREENING_SOURCE_KEY


def test_a_screening_unit_holds_the_application_and_the_entry_it_is_set_against():
    read = read_screenings()
    unit = next(u for u in read.units if u.anchor == "pair:CUST-003/sanctions-1")
    text = read.unit_text[unit.id]
    assert "Dmitri Volkonsky" in text
    assert "Dmitry Volkonskiy" in text
    assert "Karvonia arms embargo" in text


def test_the_screening_source_changes_with_any_of_its_three_files(tmp_path, monkeypatch):
    before = read_screenings().source.digest
    copy = tmp_path / "data"
    copy.mkdir()
    for name in ("applications", "sanctions_list", "pep_list"):
        (copy / f"{name}.jsonl").write_text(
            (PROJECT_ROOT / "data" / f"{name}.jsonl").read_text(), encoding="utf-8"
        )
    monkeypatch.setattr(db, "DATA_DIR", copy)
    monkeypatch.setattr("context.reader.DATA_DIR", copy)
    assert read_screenings().source.digest == before
    lines = (copy / "pep_list.jsonl").read_text().splitlines()
    (copy / "pep_list.jsonl").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    after = read_screenings()
    assert after.source.digest != before
    assert len(after.units) == 25 * 13


def test_an_application_that_is_not_there_is_named():
    with pytest.raises(ApplicationNotFoundError, match="CUST-999"):
        read_applications(["CUST-001", "CUST-999"])


def test_a_chosen_batch_reads_only_its_applications():
    read = read_applications(["CUST-002", "CUST-001"])
    assert [u.anchor for u in read.units] == ["row:CUST-001", "row:CUST-002"]
    assert len(read_screenings(["CUST-001"]).units) == 14
