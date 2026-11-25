"""The picture of a batch: applications against list entries, each screening marked by its state."""

import pytest
from kyc_fakes import ScriptedReader, reading_of
from support import new_runs, start_run

from review_app.picture import build_picture
from workflow.runs import KycRuns

ENTRIES = 14


def href(customer: str) -> str:
    return f"/x/{customer}"


@pytest.fixture(scope="module")
def batch():
    runs = new_runs()
    thread = start_run(runs)
    return runs.result(thread)


def cell(picture, customer, part):
    row = next(r for r in picture.rows if r.customer_id == customer)
    return next(c for c in row.cells if c.anchor_part == part)


def test_every_application_is_a_row_and_every_entry_a_column(batch):
    picture = build_picture(batch, settled={}, href_for=href)
    assert len(picture.rows) == 25
    assert [r.customer_id for r in picture.rows] == [f"CUST-{n:03d}" for n in range(1, 26)]
    assert all(len(r.cells) == ENTRIES for r in picture.rows)
    assert len(picture.entries) == ENTRIES
    assert [e.list for e in picture.entries] == ["sanctions"] * 8 + ["pep"] * 6
    assert [e.number for e in picture.entries] == list(range(1, 15))
    assert picture.rows[2].name == "Dmitri Volkonsky"
    assert picture.rows[2].href == "/x/CUST-003"


def test_the_count_that_closes_is_the_engines_own_accounting(batch):
    picture = build_picture(batch, settled={}, href_for=href)
    assert (picture.total, picture.accounted) == (350, 350)
    assert picture.with_facts == 18 and picture.without_facts == 332
    assert picture.count == (
        "350 of 350 screenings accounted for: 18 kept as facts and 332 with no likeness"
    )
    states = [c.state for r in picture.rows for c in r.cells]
    assert len(states) == 350
    assert sum(s != "none" for s in states) == 18


def test_an_independent_recount_of_the_state_gives_the_same_marks(batch):
    picture = build_picture(batch, settled={}, href_for=href)
    facts = [c[0] for c in batch["facts"].values() if c[0]["kind"] == "screening"]
    anchors = {f["subject"]["anchor"] for f in facts}
    marked = {
        f"pair:{r.customer_id}/{c.anchor_part}" for r in picture.rows for c in r.cells
        if c.state != "none"
    }  # fmt: skip
    assert marked == anchors
    assert len(batch["screening_reasons"]) == 332


def test_each_state_is_marked_with_its_word_and_the_evidence_for_hover(batch):
    picture = build_picture(batch, settled={}, href_for=href)
    settled = cell(picture, "CUST-016", "sanctions-4")
    assert (settled.state, settled.word) == ("settled", "Settled by the checks")
    assert "Exact name and date of birth match with Rurik Zelenko" in settled.detail
    needs = cell(picture, "CUST-018", "sanctions-5")
    assert (needs.state, needs.word) == ("needs", "Needs a person")
    assert "Ivana Strahov" in needs.detail and "1.00" in needs.detail
    near = cell(picture, "CUST-015", "pep-1")
    assert (near.state, near.word) == ("near", "Near match, needs a person")
    kept = cell(picture, "CUST-020", "pep-6")
    assert (kept.state, kept.word) == ("kept", "Kept as a fact")
    none = cell(picture, "CUST-001", "sanctions-1")
    assert (none.state, none.word) == ("none", "No likeness")
    assert none.detail.startswith("No likeness: the names score") and "Dmitry" in none.detail


def test_a_question_a_person_has_settled_is_no_longer_marked_as_waiting(batch):
    question = next(
        q for q in batch["open_questions"].values() if "pair:CUST-018/" in q["about"]["anchor"]
    )
    picture = build_picture(
        batch, settled={question["id"]: "Answered by you, on 25 November 2026"}, href_for=href
    )
    done = cell(picture, "CUST-018", "sanctions-5")
    assert (done.state, done.word) == ("answered", "Answered by a person")
    assert "Answered by you, on 25 November 2026" in done.detail
    assert cell(picture, "CUST-003", "sanctions-1").state == "needs"


def test_the_key_names_only_the_marks_in_use_and_the_entries_by_number(batch):
    picture = build_picture(batch, settled={}, href_for=href)
    assert [kind for kind, _ in picture.key] == ["settled", "needs", "near", "kept", "none"]
    first = picture.entries[0]
    assert first.name == "Dmitry Volkonskiy" and first.detail == "Karvonia arms embargo"
    assert picture.entries[8].detail == "Deputy Minister of Finance, Valdoria"


def test_a_name_that_failed_its_check_is_marked_not_screened():
    runs = KycRuns(
        models=ScriptedReader(
            readings={"CUST-001": reading_of("CUST-001", name="Sarah Mitchell-Jones")}
        )
    )
    thread = start_run(runs, ["CUST-001", "CUST-004"])
    picture = build_picture(runs.result(thread), settled={}, href_for=href)
    row = picture.rows[0]
    assert {c.state for c in row.cells} == {"not_screened"}
    assert row.name is None
    assert {c.state for c in picture.rows[1].cells} == {"none"}
    assert picture.accounted == picture.total == 28
    assert "not_screened" in [kind for kind, _ in picture.key]


def test_a_batch_of_one_application_draws_one_row():
    runs = new_runs()
    thread = start_run(runs, ["CUST-016"])
    picture = build_picture(runs.result(thread), settled={}, href_for=href)
    assert (len(picture.rows), picture.total) == (1, 14)
