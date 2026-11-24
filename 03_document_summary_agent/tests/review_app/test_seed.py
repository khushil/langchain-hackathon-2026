"""The seed: a brief waiting and a brief signed, made by the real engine from the recordings."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import pytest
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app
from fsi_common.app.offline import replay_only
from fsi_common.model import ReplayMissError
from fsi_common.records import Person
from review_app import seed as seed_module
from review_app.context import Services
from review_app.plugin import PLUGIN, build_plugin
from review_app.seed import (
    DECISIONS,
    REVIEWER,
    SEED_DATE,
    SeedDecision,
    SeedError,
    seed_compliance_brief,
)
from workflow.runs import BriefRuns


@dataclass
class Seeded:
    """A run service the seed has filled, and the services over it."""

    runs: BriefRuns
    services: Services

    def state(self, thread: str) -> dict:
        return self.runs.result(thread)

    def shape(self) -> list[dict]:
        """Everything about the runs that must be the same each time, and nothing that is not."""
        out = []
        for thread in self.runs.list_runs():
            state = self.state(thread)
            status = self.runs.status(thread)
            entry = {"status": status, "request": state["request"]}
            if status == "awaiting_review":
                request = self.runs.review_request(thread)
                entry["brief_id"] = request.brief_id
                entry["brief_digest"] = request.brief_digest
            else:
                entry["decisions"] = sorted(state["decisions"].values(), key=lambda d: d["id"])
                entry["sign_off"] = state["sign_off"]
            out.append(entry)
        return out


def make_seeded(today: str | None = None) -> Seeded:
    with replay_only():
        runs = BriefRuns()
    services = (
        Services(runs=lambda: runs)
        if today is None
        else Services(runs=lambda: runs, today=lambda: today)
    )
    seed_compliance_brief(services)
    return Seeded(runs, services)


@pytest.fixture(scope="module")
def seeded() -> Seeded:
    return make_seeded()


def page_text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def waiting_and_signed(seeded: Seeded) -> tuple[str, str]:
    """Return the waiting brief's thread and the signed brief's, whatever order they were made."""
    by_status = {seeded.runs.status(t): t for t in seeded.runs.list_runs()}
    return by_status["awaiting_review"], by_status["signed"]


def test_the_seed_leaves_one_brief_waiting_for_a_reviewer_and_one_signed_newest_first(seeded):
    threads = seeded.runs.list_runs()
    assert [seeded.runs.status(t) for t in threads] == ["signed", "awaiting_review"]
    for thread in threads:
        request = seeded.state(thread)["request"]
        assert (request["document_id"], request["firm_id"]) == ("PS26-4", "FIRM-001")
        assert request["sections"] == ["7"]


def test_the_signed_brief_carries_the_named_reviewers_decisions_each_in_their_words(seeded):
    state = seeded.state(waiting_and_signed(seeded)[1])
    sign_off = state["sign_off"]
    assert sign_off["outcome"] == "signed"
    assert sign_off["date"] == SEED_DATE
    assert sign_off["reviewer"] == {"name": "Dana Whitfield", "role": "Head of Compliance"}
    assert REVIEWER == Person(name="Dana Whitfield", role="Head of Compliance")
    decisions = list(state["decisions"].values())
    wanted = {d.fact_id: d for d in DECISIONS}
    assert len(decisions) == len(wanted) == 16
    for decision in decisions:
        assert decision["reviewer"] == sign_off["reviewer"]
        assert decision["date"] == SEED_DATE
        assert decision["subject_id"] in wanted
        assert decision["outcome"] == wanted[decision["subject_id"]].outcome
        assert decision["reason"] == wanted[decision["subject_id"]].reason


def test_every_fact_the_brief_cites_has_a_decision_in_the_fixture(seeded):
    waiting = waiting_and_signed(seeded)[0]
    cited = {c.fact.id for s in seeded.runs.review_request(waiting).statements for c in s.facts}
    assert cited == {d.fact_id for d in DECISIONS}


def test_the_waiting_brief_has_nothing_decided_on_it_and_carries_nothing_from_the_signed_one(
    seeded,
):
    waiting = waiting_and_signed(seeded)[0]
    assert seeded.state(waiting).get("decisions", {}) == {}
    assert seeded.services.drafts.get(waiting, REVIEWER).facts == {}
    request = seeded.runs.review_request(waiting)
    outcomes = {c.carry.outcome for s in request.statements for c in s.facts}
    assert outcomes == {"fresh"}


def test_the_waiting_brief_asks_the_reviewer_for_every_fact_and_the_signed_decisions_are_kept(
    seeded,
):
    app = create_app(
        AppConfig(secret=b"test", topic_folders=()), topics=[build_plugin(seeded.services)]
    )
    client = TestClient(app)
    waiting = waiting_and_signed(seeded)[0]
    review = page_text(client.get(f"/compliance-brief/runs/{waiting}/review").text)
    assert "16 facts still need your decision before it can be signed." in review
    assert "Carried:" not in review


def test_the_applications_home_and_list_show_one_waiting_and_one_signed(seeded):
    app = create_app(
        AppConfig(secret=b"test", topic_folders=()), topics=[build_plugin(seeded.services)]
    )
    client = TestClient(app)
    assert "1 brief is waiting for a reviewer." in page_text(client.get("/").text)
    topic = page_text(client.get("/compliance-brief/").text)
    assert "2 briefs so far: 1 waiting for a reviewer, 1 signed." in topic
    assert topic.count("PS26-4 for Harbour Mutual Bank, section 7") == 2


def test_starting_twice_gives_the_same_briefs_decisions_and_digests(seeded):
    again = make_seeded()
    assert again.shape() == seeded.shape()
    assert len(again.shape()) == 2


def test_the_dates_of_the_seeded_decisions_are_the_fixed_date_whatever_the_clock_says(seeded):
    later = make_seeded(today="2031-03-04")
    assert later.shape() == seeded.shape()
    signed = later.state(waiting_and_signed(later)[1])
    assert {d["date"] for d in signed["decisions"].values()} == {SEED_DATE}
    assert signed["sign_off"]["date"] == SEED_DATE


def test_the_seed_changes_neither_the_model_backend_nor_tracing_for_runs_started_later(
    monkeypatch,
):
    monkeypatch.setenv("MODEL_BACKEND", "claude-code")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    make_seeded()
    assert os.environ["MODEL_BACKEND"] == "claude-code"
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert "LANGCHAIN_TRACING_V2" not in os.environ


def test_a_missing_recording_stops_the_seed_with_the_replay_miss_named(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_RECORDINGS_DIR", str(tmp_path))
    with replay_only():
        runs = BriefRuns()
    with pytest.raises(ReplayMissError):
        seed_compliance_brief(Services(runs=lambda: runs))
    assert runs.list_runs() != [] and {runs.status(t) for t in runs.list_runs()} == {"failed"}


def test_a_fixture_that_leaves_a_cited_fact_undecided_stops_the_seed_naming_it(monkeypatch):
    left = DECISIONS[0]
    monkeypatch.setattr(seed_module, "DECISIONS", DECISIONS[1:])
    with replay_only():
        runs = BriefRuns()
    with pytest.raises(SeedError, match=re.escape(left.fact_id)):
        seed_compliance_brief(Services(runs=lambda: runs))


def test_a_fixture_decision_on_a_fact_not_on_the_brief_stops_the_seed_naming_it(monkeypatch):
    stray = SeedDecision("fact:0000000000000000", "accept", "Nothing to read.")
    monkeypatch.setattr(seed_module, "DECISIONS", (*DECISIONS, stray))
    with replay_only():
        runs = BriefRuns()
    with pytest.raises(SeedError, match="fact:0000000000000000"):
        seed_compliance_brief(Services(runs=lambda: runs))


def test_the_plug_in_makes_the_seed_when_the_application_is_started_with_the_setting():
    assert PLUGIN.name == "compliance-brief"
    assert PLUGIN.seed is not None


def test_the_seeds_wording_is_the_reviewers_and_never_a_machines():
    assert len({d.fact_id for d in DECISIONS}) == len(DECISIONS) == 16
    for decision in DECISIONS:
        assert decision.outcome in {"accept", "amend", "reject"}
        assert decision.reason.strip() and decision.reason.strip()[-1] == "."
        assert not re.search(r"\b(model|AI|assistant|Claude)\b", decision.reason, re.I)


def test_a_decision_the_review_route_refuses_stops_the_seed_with_the_routes_own_words(
    monkeypatch,
):
    empty = SeedDecision(DECISIONS[0].fact_id, "accept", "   ")
    monkeypatch.setattr(seed_module, "DECISIONS", (empty, *DECISIONS[1:]))
    with replay_only():
        runs = BriefRuns()
    with pytest.raises(
        SeedError, match=r"refused the decision on fact:3ea55dfec196c112 with 422: .*own words"
    ):
        seed_compliance_brief(Services(runs=lambda: runs))
