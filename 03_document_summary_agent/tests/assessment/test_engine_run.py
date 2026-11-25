"""The engine on the real texts with fake judges: plan, run, retries, refusals, replay order."""

from __future__ import annotations

import asyncio
import math

import pytest
from assessment.bundle import read_bundle, write_bundle
from assessment.candidates import find_candidates
from assessment.engine import (
    DEFAULT_CONCURRENCY,
    MAX_TRIES,
    JudgementRefusedError,
    plan_of,
    prepare,
    run_assessment,
)
from assessment.judge import make_request, request_digest
from assessment.profile import load_profile
from assessment.validate import COMPLIANCE_WORDS, validate_bundle
from assessment_fakes import AlwaysBadJudge, FlakyJudge, ScriptedJudge

from utils.models import MAX_CONCURRENCY

CORPUS = "harbour-mutual-bank"


@pytest.fixture(scope="module")
def prepared(texts):
    return prepare(texts, load_profile(CORPUS))


@pytest.fixture(scope="module")
def judge():
    return ScriptedJudge()


@pytest.fixture(scope="module")
def bundle(texts, prepared, judge):
    return run_assessment(CORPUS, judge, texts=texts, prepared=prepared, run="record")


def test_the_default_concurrency_is_the_models_one_limit():
    assert DEFAULT_CONCURRENCY == MAX_CONCURRENCY == 4


def test_the_plan_counts_the_calls_before_any_call_is_made(prepared):
    plan = plan_of(prepared, concurrency=4)
    applicable = sum(o.applies is True for o in prepared.register.obligations)
    assert plan.applicable == applicable == 219
    assert plan.judged + plan.by_code == applicable
    assert plan.rounds == math.ceil(plan.judged / 4)
    assert plan.by_regulation == {"DORA": 101, "AI-ACT": 21, "SS1-23": 97}
    assert str(plan.judged) in plan.line and "at 4 at a time" in plan.line


def test_every_applicable_obligation_has_a_request_or_is_assessed_by_code(prepared):
    asked = {o.obligation_id for o in prepared.judged}
    by_code = {o.obligation_id for o in prepared.by_code}
    applicable = {o.obligation_id for o in prepared.register.obligations if o.applies is True}
    assert asked | by_code == applicable and not asked & by_code


def test_a_run_gives_a_bundle_that_passes_every_check(bundle, texts):
    report = validate_bundle(bundle, texts)
    assert report.faults == []
    assert len(bundle.assessments) == 219
    assert bundle.index.run == "record" and bundle.index.scope == []


def test_each_judgement_is_keyed_by_the_digest_of_its_request(bundle):
    for j in bundle.judgements:
        assert j.request_digest == request_digest(j.request)
        assert j.role == "assess" and j.model == "fake-judge"
    assert len(bundle.judgements) == len(
        [a for a in bundle.assessments if a.assessed_by == "model"]
    )


def test_the_bundle_holds_every_part_and_writes_and_reads_back(bundle, texts, tmp_path):
    folder = write_bundle(bundle, tmp_path)
    again = read_bundle(folder)
    assert validate_bundle(again, texts).faults == []
    assert again.index == bundle.index
    assert [a.id for a in again.assessments] == [a.id for a in bundle.assessments]
    assert len(bundle.seed_matches) == 55
    assert len(bundle.clause_map) == texts.clause_count(in_force_only=True)
    assert {f.kind for f in bundle.facts} >= {"provision", "clause", "supersedes", "defines"}


def test_the_gap_report_states_one_gap_for_each_assessment_that_is_not_covered(bundle):
    open_ones = [a for a in bundle.assessments if a.state != "covered"]
    assert len(bundle.gap_report.statements) == len(open_ones)
    for statement in bundle.gap_report.statements:
        assert COMPLIANCE_WORDS.search(statement.text) is None


def test_the_run_never_exceeds_the_concurrency_it_is_given(texts, prepared):
    for limit in (1, 4):
        judge = ScriptedJudge(delay=lambda r: 0.001)
        run_assessment(CORPUS, judge, texts=texts, prepared=prepared, concurrency=limit)
        assert judge.max_in_flight == limit


def test_a_replay_matches_whatever_order_the_calls_finish_in(texts, prepared, bundle):
    slow_first = ScriptedJudge(delay=lambda r: (hash(r.obligation_id) % 7) / 2000)
    reversed_delay = ScriptedJudge(delay=lambda r: (6 - hash(r.obligation_id) % 7) / 2000)
    a = run_assessment(CORPUS, slow_first, texts=texts, prepared=prepared, run="record")
    b = run_assessment(CORPUS, reversed_delay, texts=texts, prepared=prepared, run="record")
    assert a.model_dump_json() == b.model_dump_json() == bundle.model_dump_json()


def test_the_request_an_obligation_gets_depends_on_it_and_its_candidates_only(
    texts, prepared, judge
):
    o = prepared.judged[0]
    kept = prepared.kept[o.obligation_id]
    assert make_request(o, kept, texts) == make_request(o, list(reversed(kept)), texts)


def test_an_answer_that_fails_a_check_is_asked_again_with_the_faults(texts, prepared):
    flaky = FlakyJudge(mixed=False)
    bundle = run_assessment(CORPUS, flaky, texts=texts, prepared=prepared)
    asked = {o for o, _ in flaky.calls}
    assert len(flaky.calls) == 2 * len(asked)
    retries = [faults for _, faults in flaky.calls if faults]
    assert len(retries) == len(asked)
    first = retries[0]
    assert all(f.startswith(("clause-quote-not-verbatim", "state")) for f in first)
    assert bundle.index.counts["retried calls"] == len(asked)
    assert validate_bundle(bundle, texts).faults == []


def test_an_answer_that_keeps_failing_is_refused_by_name_after_the_tries(texts, prepared):
    bad = AlwaysBadJudge(mixed=False)
    with pytest.raises(JudgementRefusedError) as raised:
        run_assessment(CORPUS, bad, texts=texts, prepared=prepared)
    message = str(raised.value)
    assert prepared.judged[0].obligation_id in message
    assert "clause-quote-not-verbatim" in message
    assert len(bad.calls) == MAX_TRIES * len(prepared.judged)


def test_a_call_that_raises_is_reported_with_the_others_finished(texts, prepared):
    class Raises(ScriptedJudge):
        async def __call__(self, request, *, faults=()):
            if request.obligation_id == prepared.judged[3].obligation_id:
                raise OSError("the call failed")
            return await super().__call__(request, faults=faults)

    judge = Raises()
    with pytest.raises(JudgementRefusedError, match="the call failed") as raised:
        run_assessment(CORPUS, judge, texts=texts, prepared=prepared)
    assert prepared.judged[3].obligation_id in str(raised.value)
    assert len(judge.calls) == len(prepared.judged) - 1


def _without_candidates(target_id, *, on_second_look):
    def finder(register, texts, graph, *, second_look):
        found = find_candidates(register, texts, graph, second_look=second_look)
        if second_look and on_second_look:
            first = find_candidates(register, texts, graph, second_look=False)
            found = [c for c in first if c.obligation_id == target_id and c.kept]
            found = [c.model_copy(update={"found_by": ["second_look", "term"]}) for c in found]
            return found
        return [c for c in found if c.obligation_id != target_id]

    return finder


def test_an_obligation_with_no_candidate_on_two_looks_is_not_covered_by_code(texts):
    profile = load_profile(CORPUS)
    base = prepare(texts, profile)
    target = base.judged[0].obligation_id
    prepared = prepare(texts, profile, finder=_without_candidates(target, on_second_look=False))
    assert target in {o.obligation_id for o in prepared.by_code}
    judge = ScriptedJudge()
    bundle = run_assessment(CORPUS, judge, texts=texts, prepared=prepared)
    one = next(a for a in bundle.assessments if a.obligation_id == target)
    assert (one.assessed_by, one.second_look, one.state) == ("code", True, "not covered")
    assert one.clause_quotes == [] and one.gap
    assert target not in {o for o, _ in judge.calls}
    assert validate_bundle(bundle, texts).faults == []


def test_a_second_look_that_finds_clauses_sends_the_obligation_to_the_judge(texts):
    profile = load_profile(CORPUS)
    base = prepare(texts, profile)
    target = base.judged[0].obligation_id
    prepared = prepare(texts, profile, finder=_without_candidates(target, on_second_look=True))
    assert target in {o.obligation_id for o in prepared.judged}
    judge = ScriptedJudge()
    bundle = run_assessment(CORPUS, judge, texts=texts, prepared=prepared)
    one = next(a for a in bundle.assessments if a.obligation_id == target)
    assert (one.assessed_by, one.second_look) == ("model", True)
    assert validate_bundle(bundle, texts).faults == []


def test_a_seed_is_matched_to_the_state_the_run_found_there(bundle):
    by_id = {a.obligation_id: a for a in bundle.assessments}
    assert {m.seed_id for m in bundle.seed_matches} >= {"DORA-01", "SS123-15", "AIA-08"}
    for m in bundle.seed_matches:
        assert all(o in by_id for o in m.obligation_ids)


def test_the_run_is_async_all_the_way_down(texts, prepared):
    async def go():
        from assessment.engine import assess_async

        return await assess_async(prepared, ScriptedJudge(mixed=False), run="record", concurrency=4)

    assert len(asyncio.run(go()).assessments) == 219


def test_a_bundle_that_fails_a_check_is_refused_before_it_is_returned(texts, prepared, monkeypatch):
    from assessment import engine
    from assessment.validate import BundleInvalidError

    monkeypatch.setattr(engine, "_clause_map", lambda prepared, assessments: [])
    with pytest.raises(BundleInvalidError, match="clause"):
        run_assessment(CORPUS, ScriptedJudge(mixed=False), texts=texts, prepared=prepared)


def test_the_bundle_records_the_digest_of_the_instructions_the_calls_were_made_under(
    bundle, tmp_path
):
    import hashlib

    from assessment.judge import INSTRUCTIONS_PATH, recorded_instructions_digest

    expected = "sha256:" + hashlib.sha256(INSTRUCTIONS_PATH.read_bytes()).hexdigest()
    assert recorded_instructions_digest(bundle.index) == expected
    assert bundle.index.instructions_digest == expected
    assert not [k for k in bundle.index.counts if "sha256" in k]
    again = read_bundle(write_bundle(bundle, tmp_path))
    assert recorded_instructions_digest(again.index) == expected


def test_a_bundle_made_before_the_digest_was_recorded_says_so(bundle):
    from assessment.judge import recorded_instructions_digest

    older = bundle.index.model_copy(update={"instructions_digest": None})
    assert recorded_instructions_digest(older) is None


def test_the_recorded_digest_follows_the_instructions_the_judge_was_built_with(
    texts, prepared, tmp_path, monkeypatch
):
    import hashlib

    from assessment import judge as judge_module
    from assessment.judge import recorded_instructions_digest

    changed = tmp_path / "assess_instructions.md"
    changed.write_text("Other instructions for the digest test.\n", encoding="utf-8")
    monkeypatch.setattr(judge_module, "INSTRUCTIONS_PATH", changed)
    run = run_assessment(CORPUS, ScriptedJudge(mixed=False), texts=texts, prepared=prepared)
    assert recorded_instructions_digest(run.index) == (
        "sha256:" + hashlib.sha256(changed.read_bytes()).hexdigest()
    )


def test_each_failed_obligation_is_named_on_its_own_line_with_the_tries_it_had(texts, prepared):
    class RaisesOnce(ScriptedJudge):
        async def __call__(self, request, *, faults=()):
            if request.obligation_id == prepared.judged[3].obligation_id:
                raise OSError("the call failed")
            return await super().__call__(request, faults=faults)

    with pytest.raises(JudgementRefusedError) as raised:
        run_assessment(CORPUS, RaisesOnce(), texts=texts, prepared=prepared)
    lines = str(raised.value).splitlines()
    assert lines[0] == "1 of 219 obligations have no usable answer:"
    assert lines[1].startswith(f"- {prepared.judged[3].obligation_id} (after 1 try: OSError")
    with pytest.raises(JudgementRefusedError) as raised:
        run_assessment(CORPUS, AlwaysBadJudge(mixed=False), texts=texts, prepared=prepared)
    lines = str(raised.value).splitlines()
    assert (
        lines[0]
        == f"{len(prepared.judged)} of {len(prepared.judged)} obligations have no usable answer:"
    )
    assert len(lines) == 1 + len(prepared.judged)
    assert all(f"(after {MAX_TRIES} tries: " in line for line in lines[1:])


def test_a_corpus_with_no_applicable_obligation_is_refused_by_name(texts, prepared):
    import dataclasses

    from assessment.engine import NothingToAssessError

    empty = dataclasses.replace(prepared, judged=[], by_code=[])
    with pytest.raises(NothingToAssessError, match="No obligation"):
        run_assessment(CORPUS, ScriptedJudge(), texts=texts, prepared=empty, seeds=[])
