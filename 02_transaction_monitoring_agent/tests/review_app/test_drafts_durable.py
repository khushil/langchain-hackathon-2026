"""Tests of a reviewer's pending work kept in a file: a store opened on it later finds the same."""

from __future__ import annotations

import threading

import pytest
from support import DANA as DANA_FIELDS
from support import TODAY, small_request

from context.questions import question_for_missing
from context.reader import read_stream
from fsi_common.records import Decision, Person
from review_app.drafts import DraftFileError, DraftStore
from utils import db

DANA = Person(**DANA_FIELDS)
OTHER = Person(name="Ravi Shah", role="Fraud Analyst")
SMALL = small_request()
FACT_A, FACT_B = (c.fact for c in SMALL.request.assessments)
STREAM = read_stream("USR-001")
QUESTION = question_for_missing(
    STREAM.unit_of["tx:TX-1002"], db.get("transactions", transaction_id="TX-1002")
)


def decision(fact, who=DANA, outcome="accept", reason="I read the paragraph."):
    return Decision.on(
        fact,
        outcome=outcome,
        reason=reason,
        reviewer=who,
        date=TODAY,
        amendment="Reworded." if outcome == "amend" else None,
    )


@pytest.fixture()
def path(tmp_path):
    return tmp_path / "drafts.sqlite"


def test_a_fact_decision_an_answer_and_an_assumption_are_found_after_a_restart(path):
    first = DraftStore(path)
    fact_decision = decision(FACT_A, outcome="amend")
    answer = Decision.on(
        QUESTION,
        outcome="answer",
        reason="From the regulator.",
        reviewer=DANA,
        date=TODAY,
        answer="Both.",
    )
    first.put_fact_decision("run-1", fact_decision)
    first.put_answer("run-1", answer)
    first.put_assumption("run-1", DANA, "question:other", "Treat it as made before 2027.")
    first.close()
    held = DraftStore(path).get("run-1", DANA)
    assert held.facts == {FACT_A.id: fact_decision}
    assert held.answers == {QUESTION.id: answer}
    assert held.assumptions == {"question:other": "Treat it as made before 2027."}


def test_a_later_decision_on_the_same_fact_replaces_the_earlier_one_after_a_restart(path):
    first = DraftStore(path)
    first.put_fact_decision("run-1", decision(FACT_A, reason="First."))
    later = decision(FACT_A, outcome="reject", reason="Second.")
    first.put_fact_decision("run-1", later)
    first.close()
    assert DraftStore(path).get("run-1", DANA).facts == {FACT_A.id: later}


def test_an_answer_and_an_assumption_on_one_question_replace_each_other_after_a_restart(path):
    answer = Decision.on(
        QUESTION,
        outcome="answer",
        reason="Why.",
        reviewer=DANA,
        date=TODAY,
        answer="Both.",
    )
    first = DraftStore(path)
    first.put_assumption("run-1", DANA, QUESTION.id, "An assumption.")
    first.put_answer("run-1", answer)
    first.close()
    held = DraftStore(path).get("run-1", DANA)
    assert held.answers == {QUESTION.id: answer} and held.assumptions == {}


def test_one_persons_work_is_not_seen_by_another_after_a_restart(path):
    first = DraftStore(path)
    first.put_fact_decision("run-1", decision(FACT_A))
    first.close()
    again = DraftStore(path)
    assert again.get("run-1", OTHER).facts == {}
    assert again.get("run-2", DANA).facts == {}


def test_clearing_a_run_removes_everyones_work_on_it_and_only_on_it_after_a_restart(path):
    first = DraftStore(path)
    first.put_fact_decision("run-1", decision(FACT_A))
    first.put_fact_decision("run-1", decision(FACT_A, who=OTHER))
    kept = decision(FACT_B)
    first.put_fact_decision("run-2", kept)
    first.clear("run-1")
    first.close()
    again = DraftStore(path)
    assert again.get("run-1", DANA).facts == {} and again.get("run-1", OTHER).facts == {}
    assert again.get("run-2", DANA).facts == {FACT_B.id: kept}


def test_a_store_with_no_file_keeps_work_in_memory_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = DraftStore()
    store.put_fact_decision("run-1", decision(FACT_A))
    assert list(tmp_path.iterdir()) == []
    assert len(store.get("run-1", DANA).facts) == 1


def test_a_file_that_is_not_a_database_is_refused_naming_it(path):
    path.write_text("this is not a database, it is a sentence of text.")
    with pytest.raises(DraftFileError, match="drafts.sqlite"):
        DraftStore(path)


def test_a_stored_decision_that_is_not_valid_is_refused_naming_the_run(path):
    first = DraftStore(path)
    first.put_fact_decision("run-1", decision(FACT_A))
    first.close()
    import sqlite3

    with sqlite3.connect(path) as conn:
        conn.execute('UPDATE drafts SET payload = \'{"schema": "nothing"}\'')
    with pytest.raises(DraftFileError, match="run-1"):
        DraftStore(path)


def test_many_threads_writing_at_once_lose_no_decision(path):
    facts = [FACT_A, FACT_B]
    store = DraftStore(path)
    failures = []

    def write(index):
        try:
            who = Person(name=f"Reviewer {index}", role="Analyst")
            for fact in facts:
                store.put_fact_decision("run-1", decision(fact, who=who))
            store.put_assumption("run-1", who, f"question:{index}", f"Assumption {index}.")
        except Exception as exc:  # collected so the test can name it
            failures.append(exc)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    store.close()
    assert failures == []
    again = DraftStore(path)
    for index in range(12):
        held = again.get("run-1", Person(name=f"Reviewer {index}", role="Analyst"))
        assert set(held.facts) == {f.id for f in facts}
        assert held.assumptions == {f"question:{index}": f"Assumption {index}."}


def test_a_stored_name_that_is_not_a_person_is_refused_as_a_draft_file_fault_naming_the_file(path):
    import sqlite3

    first = DraftStore(path)
    first.put_fact_decision("run-1", decision(FACT_A))
    first.close()
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE drafts SET person_name = ''")
    with pytest.raises(DraftFileError, match="drafts.sqlite"):
        DraftStore(path)


def test_an_answer_that_could_not_be_replaced_by_an_assumption_is_still_the_answer_after_a_restart(
    path, monkeypatch
):
    answer = Decision.on(
        QUESTION,
        outcome="answer",
        reason="Why.",
        reviewer=DANA,
        date=TODAY,
        answer="Both.",
    )
    first = DraftStore(path)
    first.put_answer("run-1", answer)

    def broken(*args, **kwargs):
        raise DraftFileError("the second statement failed")

    monkeypatch.setattr(DraftStore, "_keep", broken)
    with pytest.raises(DraftFileError, match="second statement"):
        first.put_assumption("run-1", DANA, QUESTION.id, "An assumption.")
    first.close()
    monkeypatch.undo()
    held = DraftStore(path).get("run-1", DANA)
    assert held.answers == {QUESTION.id: answer} and held.assumptions == {}
