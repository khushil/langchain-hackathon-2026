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
    PROFILE,
    QUESTIONS,
    REVIEWER,
    SEED_DATE,
    SeedError,
    seed_compliance_brief,
)
from review_app.seed_fixture import SeedDecision, SeedProfile, SeedQuestion
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
        assert "sections" not in request


def test_the_signed_brief_carries_the_named_reviewers_decisions_each_in_their_words(seeded):
    state = seeded.state(waiting_and_signed(seeded)[1])
    sign_off = state["sign_off"]
    assert sign_off["outcome"] == "signed"
    assert sign_off["date"] == SEED_DATE
    assert sign_off["reviewer"] == {"name": "Dana Whitfield", "role": "Head of Compliance"}
    assert REVIEWER == Person(name="Dana Whitfield", role="Head of Compliance")
    decisions = [d for d in state["decisions"].values() if d["subject_id"].startswith("fact:")]
    wanted = {d.fact_id: (d.outcome, d.reason) for d in DECISIONS}
    wanted |= {fid: (PROFILE.outcome, PROFILE.reason) for fid in PROFILE.fact_ids}
    assert len(decisions) == len(wanted) == 57
    assert len(PROFILE.fact_ids) == 12 and len(DECISIONS) == 45
    for decision in decisions:
        assert decision["reviewer"] == sign_off["reviewer"]
        assert decision["date"] == SEED_DATE
        assert decision["subject_id"] in wanted
        assert (decision["outcome"], decision["reason"]) == wanted[decision["subject_id"]]


def questions_by_paragraph(state: dict) -> dict[str, str]:
    """Map each open question of a run to the paragraph it is about."""
    return {q["about"]["anchor"]: i for i, q in state["open_questions"].items()}


def test_every_open_question_is_answered_or_accepted_as_an_assumption_in_the_reviewers_words(
    seeded,
):
    state = seeded.state(waiting_and_signed(seeded)[1])
    ids = questions_by_paragraph(state)
    assert (
        sorted(ids)
        == sorted(q.paragraph for q in QUESTIONS)
        == [
            "para:6.6",
            "para:7.4",
            "para:9.1",
            "para:9.4",
        ]
    )
    answers = {d["subject_id"]: d for d in state["decisions"].values() if d["outcome"] == "answer"}
    assumptions = {a["question_id"]: a["words"] for a in state["sign_off"]["assumptions"]}
    for question in QUESTIONS:
        question_id = ids[question.paragraph]
        if question.assumption:
            assert assumptions[question_id] == question.assumption
            assert question_id not in answers
        else:
            assert answers[question_id]["answer"] == question.answer
            assert answers[question_id]["reason"] == question.reason
            assert answers[question_id]["reviewer"] == state["sign_off"]["reviewer"]
            assert answers[question_id]["date"] == SEED_DATE
            assert question_id not in assumptions
    assert len(answers) == 3 and len(assumptions) == 1


def test_the_firm_profile_was_decided_once_with_one_reason_and_each_fact_one_by_one(seeded):
    state = seeded.state(waiting_and_signed(seeded)[1])
    by_subject = {d["subject_id"]: d for d in state["decisions"].values()}
    profile = {fid: by_subject[fid] for fid in PROFILE.fact_ids}
    assert len({(d["outcome"], d["reason"], d["date"]) for d in profile.values()}) == 1
    reasons = {by_subject[d.fact_id]["reason"] for d in DECISIONS}
    assert len(reasons) == len(DECISIONS) and PROFILE.reason not in reasons


def test_every_fact_the_brief_cites_has_a_decision_in_the_fixture(seeded):
    waiting = waiting_and_signed(seeded)[0]
    cited = {c.fact.id for s in seeded.runs.review_request(waiting).statements for c in s.facts}
    assert cited == set(PROFILE.fact_ids) | {d.fact_id for d in DECISIONS}
    assert len(cited) == 57


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
    assert "57 facts and 4 questions still need your decision before it can be signed." in review
    assert "Carried:" not in review
    request = seeded.runs.review_request(waiting)
    assert sorted(q.about.anchor for q in request.open_questions) == sorted(
        q.paragraph for q in QUESTIONS
    )
    assert {q.state for q in request.open_questions} == {"open"}


def test_the_applications_home_and_list_show_one_waiting_and_one_signed(seeded):
    app = create_app(
        AppConfig(secret=b"test", topic_folders=()), topics=[build_plugin(seeded.services)]
    )
    client = TestClient(app)
    assert "1 brief is waiting for a reviewer." in page_text(client.get("/").text)
    topic = page_text(client.get("/compliance-brief/").text)
    assert "2 briefs so far: 1 waiting for a reviewer, 1 signed." in topic
    assert topic.count("PS26-4 for Harbour Mutual Bank") == 2
    assert "section 7" not in topic


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


def seeding_raises(monkeypatch, **changes) -> SeedError:
    """Seed on the recordings with part of the fixture changed, and return the error."""
    for name, value in changes.items():
        monkeypatch.setattr(seed_module, name, value)
    with replay_only():
        runs = BriefRuns()
    with pytest.raises(SeedError) as caught:
        seed_compliance_brief(Services(runs=lambda: runs))
    return caught.value


def test_a_fixture_that_leaves_a_document_fact_undecided_names_its_paragraph_and_words(
    monkeypatch,
):
    left = DECISIONS[0]
    error = seeding_raises(monkeypatch, DECISIONS=DECISIONS[1:])
    assert re.search(
        re.escape(left.fact_id) + re.escape(f' ({left.paragraph}, "{left.quote[:30]}'),
        str(error),
    )
    assert "document facts on the brief with no decision in the seed" in str(error)


def test_a_fixture_that_leaves_a_profile_fact_out_names_it_as_a_profile_fact(monkeypatch):
    left = PROFILE.fact_ids[4]
    shorter = SeedProfile(
        tuple(f for f in PROFILE.fact_ids if f != left), PROFILE.outcome, PROFILE.reason
    )
    error = seeding_raises(monkeypatch, PROFILE=shorter)
    assert f"firm profile facts on the brief with no decision in the seed: {left}" in str(error)
    assert "operational_resilience_senior_manager" in str(error)


def test_a_fixture_decision_on_a_fact_not_on_the_brief_is_named_as_gone(monkeypatch):
    stray = SeedDecision(
        "fact:0000000000000000", "para:7.9", "Nothing", "accept", "Nothing to read."
    )
    error = seeding_raises(monkeypatch, DECISIONS=(*DECISIONS, stray))
    assert "document facts in the seed that are not on the brief: fact:0000000000000000" in str(
        error
    )


def test_a_profile_fact_in_the_fixture_that_is_not_on_the_brief_is_named_as_gone(monkeypatch):
    longer = SeedProfile(
        (*PROFILE.fact_ids, "fact:1111111111111111"), PROFILE.outcome, PROFILE.reason
    )
    error = seeding_raises(monkeypatch, PROFILE=longer)
    assert "firm profile facts in the seed that are not on the brief: fact:1111111111111111" in str(
        error
    )


def test_the_plug_in_makes_the_seed_when_the_application_is_started_with_the_setting():
    assert PLUGIN.name == "compliance-brief"
    assert PLUGIN.seed is not None


def test_the_seeds_wording_is_the_reviewers_and_never_a_machines():
    assert len({d.fact_id for d in DECISIONS}) == len(DECISIONS) == 45
    assert len({d.reason for d in DECISIONS}) == 45
    for decision in (*DECISIONS, PROFILE):
        assert decision.outcome in {"accept", "amend", "reject"}
        assert decision.reason.strip() and decision.reason.strip()[-1] == "."
        assert not re.search(r"\b(model|AI|assistant|Claude)\b", decision.reason, re.I)
        assert (decision.amendment is not None) == (decision.outcome == "amend")
    for question in QUESTIONS:
        words = [question.answer, question.reason, question.assumption]
        for text in (w for w in words if w):
            assert text.strip()[-1] == "."
            assert not re.search(r"\b(model|AI|assistant|Claude)\b", text, re.I)
        assert bool(question.assumption) != bool(question.answer and question.reason)
    assert any(q.assumption for q in QUESTIONS) and any(q.answer for q in QUESTIONS)


def test_a_document_decision_the_review_route_refuses_stops_the_seed_with_the_routes_own_words(
    monkeypatch,
):
    first = DECISIONS[0]
    empty = SeedDecision(first.fact_id, first.paragraph, first.quote, "accept", "   ")
    error = seeding_raises(monkeypatch, DECISIONS=(empty, *DECISIONS[1:]))
    assert re.search(
        r"refused the decision on " + re.escape(first.fact_id) + r" with 422: .*own words",
        str(error),
    )


def test_a_profile_decision_the_review_route_refuses_stops_the_seed_with_the_routes_own_words(
    monkeypatch,
):
    empty = SeedProfile(PROFILE.fact_ids, "accept", "   ")
    error = seeding_raises(monkeypatch, PROFILE=empty)
    assert re.search(r"refused the decision on the firm profile with 422: .*own words", str(error))


def test_a_fixture_that_leaves_a_question_unanswered_names_its_paragraph(monkeypatch):
    left = QUESTIONS[0]
    error = seeding_raises(monkeypatch, QUESTIONS=QUESTIONS[1:])
    assert "open questions on the brief with no answer in the seed" in str(error)
    assert left.paragraph in str(error)


def test_a_fixture_answer_to_a_question_not_on_the_brief_is_named_as_gone(monkeypatch):
    stray = SeedQuestion("para:3.9", assumption="Nothing to assume.")
    error = seeding_raises(monkeypatch, QUESTIONS=(*QUESTIONS, stray))
    assert "open questions in the seed that are not on the brief: para:3.9" in str(error)


def test_an_answer_the_review_route_refuses_stops_the_seed_with_the_routes_own_words(
    monkeypatch,
):
    first = next(q for q in QUESTIONS if q.answer)
    empty = SeedQuestion(first.paragraph, answer="  ", reason=first.reason)
    others = tuple(q for q in QUESTIONS if q is not first)
    error = seeding_raises(monkeypatch, QUESTIONS=(empty, *others))
    assert re.search(
        r"refused the answer to the question about " + re.escape(first.paragraph) + r" with 422: .*"
        r"the answer",
        str(error),
    )


def test_an_assumption_the_review_route_refuses_stops_the_seed_with_the_routes_own_words(
    monkeypatch,
):
    first = next(q for q in QUESTIONS if q.assumption)
    empty = SeedQuestion(first.paragraph, assumption="  ")
    others = tuple(q for q in QUESTIONS if q is not first)
    error = seeding_raises(monkeypatch, QUESTIONS=(empty, *others))
    assert re.search(
        r"refused the assumption for the question about "
        + re.escape(first.paragraph)
        + r" with 422: .*the assumption",
        str(error),
    )


def test_two_open_questions_about_one_paragraph_are_refused_because_the_seed_finds_by_paragraph():
    class Asked:
        def __init__(self, anchor: str) -> None:
            self.about = type("About", (), {"anchor": anchor})()
            self.question = "Is this an obligation?"

    anchors = [q.paragraph for q in QUESTIONS]
    problems = seed_module._question_problems([Asked(a) for a in (*anchors, anchors[0])])
    assert problems == ["the brief has two open questions about one paragraph"]
    assert seed_module._question_problems([Asked(a) for a in anchors]) == []
