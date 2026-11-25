"""The engine on the real headless adapter with a stand-in for the process: record, then replay."""

from __future__ import annotations

import asyncio

import pytest
from assessment.engine import JudgementRefusedError, prepare, run_assessment
from assessment.judge import ModelJudge, make_request
from assessment.profile import load_profile
from assessment_fakes import ScriptedJudge, StandInClaude

from fsi_common.model import ChatClaudeHeadless

CORPUS = "harbour-mutual-bank"


@pytest.fixture(scope="module")
def prepared(texts):
    return prepare(texts, load_profile(CORPUS))


@pytest.fixture(scope="module")
def answers(prepared, texts):
    judge = ScriptedJudge()
    out = {}
    for o in prepared.judged:
        request = make_request(o, prepared.kept[o.obligation_id], texts)
        out[o.obligation_id] = asyncio.run(judge(request))
    return out


def _models(mode, folder, runner):
    chat = ChatClaudeHeadless(
        model="claude-sonnet-5-5",
        effort="medium",
        mode=mode,
        recordings_dir=folder,
        runner=runner,
    )
    return lambda role: chat


@pytest.fixture(scope="module")
def recorded(texts, prepared, answers, tmp_path_factory):
    folder = tmp_path_factory.mktemp("recordings")
    process = StandInClaude(answers)
    bundle = run_assessment(
        CORPUS,
        ModelJudge(_models("record", folder, process)),
        texts=texts,
        prepared=prepared,
        run="record",
    )
    return bundle, folder, process


def test_a_record_run_makes_one_call_for_each_applicable_obligation(recorded, prepared):
    _, folder, process = recorded
    assert len(process.calls) == len(prepared.judged) == 219
    assert len(list(folder.glob("*.json"))) == 219
    argv, stdin = process.calls[0]
    assert "--json-schema" in argv
    assert "Words of the provision:" in stdin


def test_the_answers_come_back_through_the_adapter_unchanged(recorded, answers):
    bundle, _, _ = recorded
    by_id = {j.request.obligation_id: j.answer for j in bundle.judgements}
    assert by_id == answers


def test_a_replay_with_no_process_gives_the_same_bundle(texts, prepared, recorded):
    bundle, folder, _ = recorded
    again = run_assessment(
        CORPUS,
        ModelJudge(_models("replay", folder, None)),
        texts=texts,
        prepared=prepared,
        run="replay",
    )
    index = again.index.model_copy(update={"run": "record"})
    assert again.model_copy(update={"index": index}).model_dump_json() == bundle.model_dump_json()


def test_a_replay_of_a_folder_with_no_recording_names_the_obligations(texts, prepared, tmp_path):
    with pytest.raises(JudgementRefusedError, match="ReplayMissError"):
        run_assessment(
            CORPUS,
            ModelJudge(_models("replay", tmp_path, None)),
            texts=texts,
            prepared=prepared,
            run="replay",
        )
