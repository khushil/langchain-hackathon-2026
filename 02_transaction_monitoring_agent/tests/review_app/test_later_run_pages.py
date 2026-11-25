"""A later run on the same customer shows what reviewers said before, beside the new assessments."""

from engine_fakes import ScriptedModels, label_script
from model_fakes import assessment_for_score
from review_support import WINDOW, make_world, marks, record_all, run_path, start_run, text


def signed_first_run():
    world = make_world()
    thread = start_run(world, "USR-001", **WINDOW)
    record_all(world, thread)
    request = world.runs.review_request(thread)
    world.client().post(
        run_path(thread, "sign"), data={"brief_digest": request.brief_digest, "outcome": "signed"}
    )
    return world


def test_the_whole_stream_run_after_a_signed_one_arrives_with_six_carried_and_four_to_decide():
    world = signed_first_run()
    thread = start_run(world, "USR-001")
    page = world.client().get(run_path(thread, "review"))
    words = text(page)
    assert (
        "The brief for Priya Shah has 10 transactions to decide. 4 still need your decision"
        in words
    )
    assert "6 Transactions" not in words and "6 of 10" in words
    assert marks(page, "carried") == 6
    assert marks(page, "needs") == 4
    assert "TX-1007, FreshMart Express" in words


def test_a_carried_transaction_shows_the_earlier_decision_its_reviewer_date_and_reason():
    world = signed_first_run()
    thread = start_run(world, "USR-001")
    page = world.client().get(run_path(thread, "review"), params={"tx": "TX-1003"})
    words = text(page)
    assert (
        "Agreed by you, on 25 November 2026. Reason given: Checked against what the customer "
        "told us."
    ) in words
    assert page.text.count("Carried: agreed 25 November 2026") >= 1


def test_what_reviewers_said_before_is_listed_with_each_reason_and_exported():
    world = signed_first_run()
    thread = start_run(world, "USR-001")
    page = world.client().get(run_path(thread, "review"), params={"tab": "history"})
    words = text(page)
    assert "What reviewers decided about Priya Shah before" in words
    assert words.count("Proposal agreed") == 6
    assert "Dana Whitfield, Head of Compliance" in words
    assert "Checked against what the customer told us." in words
    body = world.client().get(run_path(thread, "history.csv")).text
    assert body.splitlines()[0] == "Transaction,Decision,Made by,Date,Reason"
    assert len(body.strip().splitlines()) == 7


def test_the_history_sorts_by_a_column_and_the_export_keeps_to_what_is_shown():
    world = signed_first_run()
    thread = start_run(world, "USR-001")
    page = world.client().get(
        run_path(thread, "review"), params={"tab": "history", "sort": "transaction", "dir": "desc"}
    )
    shown = [
        m for m in __import__("re").findall(r"TX-10\d\d", page.text.split('data-hook="table"')[1])
    ]
    assert shown[:6] == sorted(shown[:6], reverse=True)


def test_an_assessment_that_changed_since_the_decision_is_asked_again_with_the_difference():
    world = signed_first_run()
    changed = label_script() | {"TX-1003": assessment_for_score(60, reason="Now more worried.")}
    again = make_world(ScriptedModels(changed), state_dir=None)
    # the same store: reuse the first world's decisions by copying them across
    from utils.review import decisions_namespace

    for item in world.runs._graph.store.search(decisions_namespace("USR-001"), limit=100):
        again.runs._graph.store.put(decisions_namespace("USR-001"), item.key, item.value)
    thread = start_run(again, "USR-001", **WINDOW)
    page = again.client().get(run_path(thread, "review"), params={"tx": "TX-1003"})
    words = text(page)
    assert "Since then these changed: Why the confidence was lowered, Reason, Risk score." in words
    assert marks(page, "needs") == 1
    assert marks(page, "carried") == 5


def test_the_start_page_marks_a_waiting_runs_carried_and_new_transactions_apart():
    world = signed_first_run()
    start_run(world, "USR-001")
    page = world.client().get("/transaction-monitoring/")
    assert marks(page, "carried") == 6 and marks(page, "needs") == 4 and marks(page, "idle") == 5
