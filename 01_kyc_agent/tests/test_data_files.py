"""The applications and the lists are the starter's, and the units read from them match them."""

import json

from context.reader import entries_of, read_applications, read_screenings
from fsi_common.ids import digest_bytes, digest_text
from utils import PROJECT_ROOT, db

DATA = PROJECT_ROOT / "data"


def test_the_starters_tables_hold_25_applications_8_sanctions_entries_and_6_pep_entries():
    assert len(db.table("applications")) == 25
    assert len(db.table("sanctions_list")) == 8
    assert len(db.table("pep_list")) == 6
    ids = [r["customer_id"] for r in db.table("applications")]
    assert ids == [f"CUST-{n:03d}" for n in range(1, 26)]


def test_the_source_digests_are_the_files_digests():
    applications = read_applications().source
    assert applications.digest == digest_bytes((DATA / "applications.jsonl").read_bytes())
    screenings = read_screenings().source
    assert screenings.digest != applications.digest


def test_each_application_unit_is_the_text_of_its_row():
    read = read_applications()
    rows = {r["customer_id"]: r["application"] for r in db.table("applications")}
    for unit in read.units:
        text = rows[unit.anchor.partition(":")[2]]
        assert read.unit_text[unit.id] == text
        assert unit.text_digest == digest_text(text)


def test_every_screening_unit_holds_its_applications_text_and_its_entrys_line():
    read = read_screenings()
    lines = [line for e in entries_of() for line in [e.line]]
    assert len(read.units) == 25 * len(lines) == 350
    for unit in read.units:
        text = read.unit_text[unit.id]
        assert any(line in text for line in lines)
        customer_id = unit.anchor.partition(":")[2].partition("/")[0]
        assert db.get("applications", customer_id=customer_id)["application"] in text


def test_the_lists_hold_the_entries_the_starter_wrote():
    entries = entries_of()
    assert [e.list for e in entries] == ["sanctions"] * 8 + ["pep"] * 6
    sanctions = [
        json.loads(line) for line in (DATA / "sanctions_list.jsonl").read_text().splitlines()
    ]
    assert [e.name for e in entries[:8]] == [r["name"] for r in sanctions]
