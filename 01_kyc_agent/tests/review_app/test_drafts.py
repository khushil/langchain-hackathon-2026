"""A reviewer's pending work: one person's own, replaced by a later word, found after a restart."""

import sqlite3

import pytest
from support import DANA, SAM, SMALL, TODAY, new_runs, start_run

from fsi_common.records import Decision
from review_app.drafts import DraftFileError, DraftStore


@pytest.fixture(scope="module")
def records():
    runs = new_runs()
    request = runs.review_request(start_run(runs, SMALL))
    proposal = next(
        c.fact for s in request.statements for c in s.facts if c.fact.kind == "proposal"
    )
    return proposal, request.open_questions[0]


def accept(proposal, who=DANA, reason="Checked."):
    return Decision.on(proposal, outcome="accept", reason=reason, reviewer=who, date=TODAY)


def answer(question, who=DANA):
    return Decision.on(
        question, outcome="answer", answer="Same.", reason="Dates.", reviewer=who, date=TODAY
    )


def test_a_decision_an_answer_and_an_assumption_are_found_after_a_restart(tmp_path, records):
    proposal, question = records
    path = tmp_path / "drafts.sqlite"
    first = DraftStore(path)
    first.put_fact_decision("t", accept(proposal))
    first.put_answer("t", answer(question))
    first.put_assumption("t", DANA, "question:other", "Assume it.")
    first.close()
    held = DraftStore(path).get("t", DANA)
    assert held.facts == {proposal.id: accept(proposal)}
    assert held.answers == {question.id: answer(question)}
    assert held.assumptions == {"question:other": "Assume it."}


def test_a_later_decision_replaces_the_earlier_and_an_answer_replaces_an_assumption(records):
    proposal, question = records
    store = DraftStore()
    store.put_fact_decision("t", accept(proposal, reason="First."))
    store.put_fact_decision("t", accept(proposal, reason="Second."))
    assert store.get("t", DANA).facts[proposal.id].reason == "Second."
    store.put_assumption("t", DANA, question.id, "Assume.")
    store.put_answer("t", answer(question))
    held = store.get("t", DANA)
    assert question.id in held.answers and question.id not in held.assumptions
    store.put_assumption("t", DANA, question.id, "Assume again.")
    assert question.id not in store.get("t", DANA).answers


def test_work_is_one_persons_own_and_nobody_signed_in_holds_none(records):
    proposal, _ = records
    store = DraftStore()
    store.put_fact_decision("t", accept(proposal))
    assert store.get("t", SAM).facts == {} and store.get("t", None).facts == {}
    assert store.get("other-run", DANA).facts == {}


def test_a_copy_is_returned_so_a_reader_cannot_change_the_store(records):
    proposal, _ = records
    store = DraftStore()
    store.put_fact_decision("t", accept(proposal))
    store.get("t", DANA).facts.clear()
    assert proposal.id in store.get("t", DANA).facts


def test_clearing_a_run_drops_everyones_work_in_memory_and_in_the_file(tmp_path, records):
    proposal, _ = records
    path = tmp_path / "drafts.sqlite"
    store = DraftStore(path)
    store.put_fact_decision("t", accept(proposal))
    store.put_fact_decision("t", accept(proposal, who=SAM))
    store.clear("t")
    store.close()
    again = DraftStore(path)
    assert again.get("t", DANA).facts == {} and again.get("t", SAM).facts == {}


def test_a_file_that_is_not_a_database_is_refused_in_words(tmp_path):
    path = tmp_path / "drafts.sqlite"
    path.write_text("this is not a database")
    with pytest.raises(DraftFileError, match="cannot be used as a database"):
        DraftStore(path)


def test_a_held_decision_that_is_not_valid_is_refused_naming_whose_it_is(tmp_path, records):
    path = tmp_path / "drafts.sqlite"
    DraftStore(path).close()
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO drafts VALUES "
            "('t', 'Dana Whitfield', 'Head of Compliance', 'fact', 'k', '{}')"
        )
    with pytest.raises(DraftFileError, match="Dana Whitfield on run t"):
        DraftStore(path)


def test_a_write_to_a_closed_store_is_kept_in_memory_only_and_never_reaches_the_file(
    tmp_path, records
):
    proposal, _ = records
    path = tmp_path / "drafts.sqlite"
    store = DraftStore(path)
    store.close()
    store.put_fact_decision("t", accept(proposal))
    assert store.get("t", DANA).facts == {proposal.id: accept(proposal)}
    assert DraftStore(path).get("t", DANA).facts == {}
