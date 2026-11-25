"""The starting work: a run signed through the review routes and a run waiting for a reviewer."""

import json

import pytest
from engine_fakes import ScriptedModels, label_script
from model_fakes import assessment_for_score
from review_support import make_world, marks, record_all, run_path, start_run, text

from fsi_common.app import SeedError
from fsi_common.records import Decision
from review_app.context import Services
from review_app.drafts import DraftStore
from review_app.plugin import build_plugin
from review_app.seed import MARKER_FILE, SEED_DATE, seed_identity, seed_transaction_monitoring
from review_app.seed_fixture import DECISIONS
from utils import db
from workflow.runs import MonitorRuns


def seeded_world(models=None):
    world = make_world(models)
    seed_transaction_monitoring(world.services, build_plugin)
    return world


def statuses(world):
    runs = world.runs
    return [runs.status(t) for t in reversed(runs.list_runs())]


def test_the_seed_makes_a_signed_run_first_and_a_waiting_run_after_it():
    world = seeded_world()
    assert statuses(world) == ["signed", "awaiting_review"]


def test_the_signed_run_stands_on_the_fixtures_decisions_made_by_the_route_by_the_named_person():
    world = seeded_world()
    signed = world.runs.list_runs()[-1]
    held = world.runs.result(signed)
    decisions = [Decision.model_validate(d) for d in held["decisions"].values()]
    assert len(decisions) == len(DECISIONS) == 6
    assert {(d.reviewer.name, d.reviewer.role, d.date) for d in decisions} == {
        ("Dana Whitfield", "Head of Compliance", SEED_DATE)
    }
    by_tx = {d.judged["subject"]["anchor"].partition(":")[2]: d for d in decisions}
    for seeded in DECISIONS:
        assert by_tx[seeded.tx_id].reason == seeded.reason
        assert by_tx[seeded.tx_id].outcome == seeded.outcome
    assert held["sign_off"]["reviewer"]["name"] == "Dana Whitfield"
    assert held["sign_off"]["date"] == SEED_DATE


def test_the_reviewers_reply_the_starter_scripted_is_used_word_for_word():
    reply = db.get("reviewer_answers", transaction_id="TX-1003")
    seeded = next(d for d in DECISIONS if d.tx_id == "TX-1003")
    assert seeded.reason == reply["note"]
    assert seeded.proposal == reply["decision"]


def test_the_waiting_run_reads_the_whole_stream_with_the_first_six_decided_and_four_to_decide():
    world = seeded_world()
    waiting = world.runs.list_runs()[0]
    page = world.client().get(run_path(waiting, "review"))
    assert "The brief for Priya Shah has 10 transactions to decide. 4 still need your decision" in (
        text(page)
    )
    assert marks(page, "carried") == 6 and marks(page, "needs") == 4


def test_the_home_count_is_the_waiting_run_and_nothing_else():
    world = seeded_world()
    plugin = build_plugin(world.services)
    assert plugin.waiting() == 1
    assert plugin.waiting_noun == "customer review"


def test_a_proposal_the_fixture_was_not_written_for_stops_the_seed_naming_the_transaction():
    other = label_script() | {"TX-1005": assessment_for_score(10)}
    world = make_world(ScriptedModels(other))
    with pytest.raises(SeedError, match=r"TX-1005 was proposed as approve.*written for block"):
        seed_transaction_monitoring(world.services, build_plugin)


def test_a_question_on_the_recorded_brief_stops_the_seed_because_the_fixture_has_no_answer():
    world = make_world(ScriptedModels(label_script() | {"TX-1002": None}))
    with pytest.raises(SeedError, match="1 open question"):
        seed_transaction_monitoring(world.services, build_plugin)


def test_a_missing_recording_stops_the_seed_by_name(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_RECORDINGS_DIR", str(tmp_path))
    runs = MonitorRuns()
    services = Services(runs=lambda: runs, drafts=DraftStore(), today=lambda: SEED_DATE)
    from fsi_common.model import ReplayMissError

    with pytest.raises(ReplayMissError, match="no recording"):
        seed_transaction_monitoring(services, build_plugin)


def durable_services(folder):
    runs = MonitorRuns(models=ScriptedModels(), state_dir=folder)
    return Services(
        runs=lambda: runs,
        drafts=DraftStore(folder / "drafts.sqlite"),
        today=lambda: SEED_DATE,
        state_dir=folder,
    ), runs


def test_a_durable_seed_leaves_a_marker_and_a_restart_adds_no_second_copy(tmp_path):
    folder = tmp_path / "state"
    services, runs = durable_services(folder)
    seed_transaction_monitoring(services, build_plugin)
    marker = json.loads((folder / MARKER_FILE).read_text())
    assert marker == {"seed": "transaction-monitoring", "digest": seed_identity()}
    runs.close()
    again, later = durable_services(folder)
    seed_transaction_monitoring(again, build_plugin)
    assert len(later.list_runs()) == 2
    later.close()


def test_a_state_folder_with_runs_and_no_marker_is_refused_in_words(tmp_path):
    folder = tmp_path / "state"
    services, runs = durable_services(folder)
    thread = runs.start({"user_id": "USR-001", "request": "x", "end": "2026-10-19"})
    from review_support import wait_for

    wait_for(runs, thread, {"awaiting_review"})
    with pytest.raises(SeedError, match="holds runs that this start did not make"):
        seed_transaction_monitoring(services, build_plugin)
    runs.close()


def test_a_marker_made_from_other_recordings_is_refused(tmp_path):
    folder = tmp_path / "state"
    services, runs = durable_services(folder)
    seed_transaction_monitoring(services, build_plugin)
    (folder / MARKER_FILE).write_text(json.dumps({"seed": "transaction-monitoring", "digest": "x"}))
    runs.close()
    again, later = durable_services(folder)
    with pytest.raises(SeedError, match="delete the folder"):
        seed_transaction_monitoring(again, build_plugin)
    later.close()


def test_the_waiting_count_is_the_runs_at_the_review_and_falls_when_one_is_signed():
    world = make_world()
    plugin = build_plugin(world.services)
    assert plugin.waiting() == 0
    first = start_run(world, "USR-001", end="2026-10-19")
    start_run(world, "USR-002")
    assert plugin.waiting() == 2
    record_all(world, first)
    request = world.runs.review_request(first)
    world.client().post(
        run_path(first, "sign"), data={"brief_digest": request.brief_digest, "outcome": "signed"}
    )
    assert plugin.waiting() == 1
