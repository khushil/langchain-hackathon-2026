"""A run over some of the regulations: its plan, bundle, printed lines and replay from recordings.

The open part (DORA and the AI Act) is assessed and replayed on a clean clone with no closed text.
The regulation left out is recorded in the bundle with its reason and the commands that bring it
in, and nothing of its text is in the bundle.
"""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest
from assessment.__main__ import main
from assessment.bundle import read_bundle, write_bundle
from assessment.engine import (
    SS123_REASON,
    plan_of,
    prepare,
    run_assessment,
)
from assessment.judge import ModelJudge, make_request, request_digest
from assessment.profile import load_profile
from assessment.records import JudgementRequest
from assessment.texts import TextIndex, load_texts
from assessment.validate import validate_bundle
from assessment_fakes import ScriptedJudge, StandInClaude

from context.errors import ContextError
from fsi_common.model import ChatClaudeHeadless

CORPUS = "harbour-mutual-bank"
OPEN = ("DORA", "AI-ACT")
REASON = (
    "its publisher allows personal and internal use only, so its text and the recordings that "
    "carry it are not held in this repository"
)


def _refuse(address: str, headers: object) -> bytes:
    raise OSError(f"no network call is made here ({address})")


@pytest.fixture(scope="module")
def open_texts(texts: TextIndex) -> TextIndex:
    return texts.only(OPEN)


@pytest.fixture(scope="module")
def open_prepared(open_texts):
    return prepare(open_texts, load_profile(CORPUS))


@pytest.fixture(scope="module")
def full_prepared(texts):
    return prepare(texts, load_profile(CORPUS))


@pytest.fixture
def loader(texts):
    def load(corpus: str, regulations: tuple[str, ...] | None = None) -> TextIndex:
        return texts.only(regulations) if regulations else texts

    return load


def _never():
    raise AssertionError("a judge was made before the plan was printed")


# Reading only the regulations named


def test_load_texts_reads_only_the_regulations_named_and_needs_no_closed_text(tmp_path):
    read = load_texts(CORPUS, regulations=OPEN, cache_dir=tmp_path, opener=_refuse)
    assert list(read.regulations) == list(OPEN)
    assert read.locate(read.regulation_source("DORA").id) == ("regulation", "DORA")
    assert read.regulation_source("DORA").id in {s for s in read._by_source}


def test_a_closed_text_that_is_not_held_is_asked_for_only_when_it_is_named(tmp_path):
    with pytest.raises(ContextError, match="no network call"):
        load_texts(CORPUS, regulations=("SS1-23",), cache_dir=tmp_path, opener=_refuse)


def test_an_unknown_regulation_is_refused_by_name(tmp_path):
    with pytest.raises(ContextError, match="NOPE"):
        load_texts(CORPUS, regulations=("DORA", "NOPE"), cache_dir=tmp_path, opener=_refuse)


def test_only_keeps_the_corpus_and_drops_the_other_regulations_places(texts, open_texts):
    ss = texts.regulation_source("SS1-23").id
    assert texts.locate(ss) == ("regulation", "SS1-23")
    assert open_texts.locate(ss) is None
    assert open_texts.clauses == texts.clauses
    assert "SS1-23" not in open_texts.regulations


# The register, the graph, the plan and the requests


def test_the_register_holds_only_the_included_regulations(open_prepared):
    keys = {o.regulation for o in open_prepared.register.obligations}
    assert keys == set(OPEN)
    assert {d.regulation for d in open_prepared.register.dispositions} == set(OPEN)
    assert sum(o.applies is True for o in open_prepared.register.obligations) == 122


def test_the_plan_counts_the_open_calls_and_says_what_is_not_included(open_prepared):
    plan = plan_of(open_prepared)
    assert plan.applicable == plan.judged + plan.by_code == 122
    assert plan.by_regulation == {"DORA": 101, "AI-ACT": 21}
    assert plan.rounds == 31


def test_no_graph_link_ends_in_a_regulation_that_is_left_out(open_prepared, open_texts, texts):
    ss = texts.regulation_source("SS1-23").id
    for fact in open_prepared.graph:
        assert fact.subject.source_id != ss
        assert fact.attributes["object_source_id"] != ss


def test_a_partial_run_asks_the_requests_a_whole_run_asks_so_whole_recordings_replay(
    open_prepared, full_prepared, open_texts, texts
):
    def digests(prepared, source: TextIndex) -> dict[str, str]:
        return {
            o.obligation_id: request_digest(make_request(o, prepared.kept[o.obligation_id], source))
            for o in prepared.judged
            if o.regulation in OPEN
        }

    mine = digests(open_prepared, open_texts)
    whole = digests(full_prepared, texts)
    assert len(mine) == len(whole) == 122
    assert mine == whole


# The bundle


@pytest.fixture(scope="module")
def judge():
    return ScriptedJudge()


@pytest.fixture(scope="module")
def bundle(open_texts, open_prepared, judge):
    return run_assessment(
        CORPUS, judge, texts=open_texts, prepared=open_prepared, run="record", concurrency=4
    )


def test_the_bundle_assesses_the_open_regulations_and_passes_every_check(bundle, open_texts):
    assert len(bundle.assessments) == 122
    assert {a.regulation for a in bundle.assessments} == set(OPEN)
    assert validate_bundle(bundle, open_texts).faults == []
    assert bundle.index.scope == []
    assert bundle.index.run == "record"


def test_the_index_records_the_regulation_left_out_with_its_reason_and_its_commands(bundle):
    (left,) = bundle.index.not_included
    assert left.regulation == "SS1-23"
    assert left.reason == REASON == SS123_REASON
    assert any(c == "make regulations-check" for c in left.commands)
    record = next(c for c in left.commands if "MODEL_BACKEND=record" in c)
    assert "python -m assessment run harbour-mutual-bank" in record
    assert "--regulations SS1-23" in record and "MODEL_RECORDINGS_DIR=" in record


def test_a_regulation_open_to_all_that_is_left_out_is_recorded_with_its_own_reason(texts, judge):
    only_dora = texts.only(("DORA",))
    bundle = run_assessment(
        CORPUS,
        judge,
        texts=only_dora,
        prepared=prepare(only_dora, load_profile(CORPUS)),
        run="record",
    )
    left = {n.regulation: n for n in bundle.index.not_included}
    assert set(left) == {"AI-ACT", "SS1-23"}
    assert left["SS1-23"].reason == REASON
    assert "--regulations" in left["AI-ACT"].reason and left["AI-ACT"].reason != REASON
    assert any("--regulations AI-ACT" in c for c in left["AI-ACT"].commands)


def test_a_whole_run_records_nothing_as_left_out(texts, full_prepared, judge):
    bundle = run_assessment(
        CORPUS, judge, texts=texts, prepared=full_prepared, run="record", concurrency=4
    )
    assert bundle.index.not_included == []
    assert len(bundle.assessments) == 219


def test_nothing_of_the_regulation_left_out_is_in_the_bundle(bundle, texts):
    ss = texts.regulation_source("SS1-23").id
    assert ss not in bundle.index.source_ids
    assert all(f.subject.source_id != ss for f in bundle.facts)
    assert all(f.attributes.get("object_source_id") != ss for f in bundle.facts)
    assert all(o.regulation != "SS1-23" for o in bundle.obligation_register.obligations)
    assert "SS1-23" not in bundle.obligation_register.regulation_digests
    assert {m.regulation for m in bundle.seed_matches} == set(OPEN)
    assert len(bundle.seed_matches) == 37


def test_the_index_and_its_reason_survive_a_round_trip_through_the_files(bundle, tmp_path):
    folder = write_bundle(bundle, tmp_path)
    again = read_bundle(folder)
    assert again.index.not_included == bundle.index.not_included
    assert (folder / "bundle.json").read_text("utf-8").count(REASON) == 1


def test_the_gap_report_names_only_the_regulations_in_the_run(bundle):
    request = bundle.gap_report.request
    assert "DORA" in request and "the AI Act" in request and "SS1/23" not in request


# The command line


def test_plan_takes_the_option_and_names_what_is_not_included(loader, capsys, monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "replay")
    code = main(
        ["plan", CORPUS, "--regulations", "DORA,AI-ACT"], judge_factory=_never, loader=loader
    )
    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out[0].startswith("Plan: 122 applicable obligations, 122 judgement calls")
    assert "DORA 101" in out[1] and "AI Act 21" in out[1] and "SS1/23" not in out[1]
    assert out.count("Regulations not included: SS1/23") == 1


def test_the_option_takes_the_names_in_any_case_and_the_ways_people_write_them(
    loader, capsys, monkeypatch
):
    monkeypatch.setenv("MODEL_BACKEND", "replay")
    for given in ("dora,ai-act", "DORA, AI Act", "ai_act,dora"):
        code = main(["plan", CORPUS, "--regulations", given], judge_factory=_never, loader=loader)
        out = capsys.readouterr().out
        assert code == 0 and "122 applicable" in out, given


@pytest.mark.parametrize("given", ["DORA,NOPE", "", "  ,"])
def test_a_bad_option_exits_2_and_names_the_regulations_there_are(
    loader, capsys, monkeypatch, given
):
    monkeypatch.setenv("MODEL_BACKEND", "replay")
    code = main(["plan", CORPUS, "--regulations", given], judge_factory=_never, loader=loader)
    err = capsys.readouterr().err
    assert code == 2
    assert "DORA" in err and "AI-ACT" in err and "SS1-23" in err


def test_run_with_the_option_writes_a_bundle_and_prints_which_regulations_are_not_included(
    loader, capsys, monkeypatch, tmp_path
):
    monkeypatch.setenv("MODEL_BACKEND", "record")
    code = main(
        ["run", CORPUS, "--regulations", "DORA,AI-ACT", "--out", str(tmp_path)],
        judge_factory=lambda: ScriptedJudge(),
        loader=loader,
    )
    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out.count("Regulations not included: SS1/23") == 1
    assert out.index("Regulations not included: SS1/23") > out.index(
        next(x for x in out if x.startswith("Plan: "))
    )
    assert not any("[SS1/23]" in line for line in out)
    assert "Obligation register: 1585 obligations, 122 apply to the firm" not in out
    registers = [x for x in out if x.startswith("Obligation register: ")]
    assert registers and registers[0].endswith(", 122 apply to the firm")
    assert any(x.startswith("Assessments: 122 applicable obligations assessed: ") for x in out)
    assert any(
        x.startswith("seeded_gaps_found [DORA]: ") and x.endswith(" of 12 seeded gaps") for x in out
    )
    assert any(
        x.startswith("seeded_gaps_found [AI Act]: ") and x.endswith(" of 5 seeded gaps")
        for x in out
    )
    assert any(
        x.startswith("seeded_gaps_found [all]: ") and x.endswith(" of 17 seeded gaps") for x in out
    )
    assert any(
        x.startswith("false_gaps [all]: ") and x.endswith(" of 20 seeds the labels hold as covered")
        for x in out
    )
    index = read_bundle(tmp_path / CORPUS).index
    assert [n.regulation for n in index.not_included] == ["SS1-23"]


def test_a_whole_run_prints_no_line_about_what_is_not_included(
    loader, capsys, monkeypatch, tmp_path
):
    monkeypatch.setenv("MODEL_BACKEND", "record")
    main(
        ["run", CORPUS, "--out", str(tmp_path)],
        judge_factory=lambda: ScriptedJudge(),
        loader=loader,
    )
    assert "not included" not in capsys.readouterr().out


# Replay from a recordings folder, with a stand-in for claude that logs any call


def _stand_in_claude(folder: Path) -> tuple[Path, Path]:
    """Write an executable named ``claude`` that logs each call and fails; return it and its log."""
    folder.mkdir()
    log = folder / "calls.log"
    script = folder / "claude"
    script.write_text(f'#!/bin/sh\necho "called: $*" >> "{log}"\nexit 1\n', "utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script, log


def _record_folder(open_texts, open_prepared, tmp_path_factory) -> Path:
    """Record the open run's calls with a fake judge's answers, through the real adapter."""
    judge = ScriptedJudge()
    answers = {
        o.obligation_id: asyncio.run(
            judge(make_request(o, open_prepared.kept[o.obligation_id], open_texts))
        )
        for o in open_prepared.judged
    }
    folder = tmp_path_factory.mktemp("recordings")
    chat = ChatClaudeHeadless(
        model="claude-sonnet-5-5",
        effort="medium",
        mode="record",
        recordings_dir=folder,
        runner=StandInClaude(answers),
    )
    run_assessment(
        CORPUS,
        ModelJudge(lambda role: chat),
        texts=open_texts,
        prepared=open_prepared,
        run="record",
    )
    return folder


@pytest.fixture(scope="module")
def recordings(open_texts, open_prepared, tmp_path_factory):
    return _record_folder(open_texts, open_prepared, tmp_path_factory)


def _env(monkeypatch, bin_dir: Path, recordings: Path, mode: str) -> None:
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("MODEL_BACKEND", mode)
    monkeypatch.setenv("MODEL_RECORDINGS_DIR", str(recordings))
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)


def test_the_stand_in_logs_a_call_when_one_is_made(
    monkeypatch, tmp_path, open_prepared, open_texts
):
    """The control: with the record backend and no recording the stand-in is called and logs."""
    script, log = _stand_in_claude(tmp_path / "bin")
    _env(monkeypatch, script.parent, tmp_path / "empty", "record")
    o = open_prepared.judged[0]
    request: JudgementRequest = make_request(o, open_prepared.kept[o.obligation_id], open_texts)
    with pytest.raises(Exception):  # the stand-in exits 1, which is the point of the control
        asyncio.run(ModelJudge()(request))
    assert log.read_text("utf-8").count("called:") >= 1


def test_the_open_part_replays_from_a_folder_with_no_call_to_claude(
    loader, capsys, monkeypatch, tmp_path, recordings
):
    script, log = _stand_in_claude(tmp_path / "bin")
    _env(monkeypatch, script.parent, recordings, "replay")
    code = main(
        ["run", CORPUS, "--regulations", "DORA,AI-ACT", "--out", str(tmp_path / "out")],
        loader=loader,
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert not log.exists() or log.read_text("utf-8") == ""
    bundle = read_bundle(tmp_path / "out" / CORPUS)
    assert bundle.index.run == "replay"
    assert len(bundle.judgements) == 122
    assert [n.regulation for n in bundle.index.not_included] == ["SS1-23"]
    assert "Regulations not included: SS1/23" in captured.out


def test_a_replay_with_a_recording_missing_fails_and_still_makes_no_call(
    loader, capsys, monkeypatch, tmp_path, recordings
):
    folder = tmp_path / "partial"
    folder.mkdir()
    kept = sorted(recordings.glob("*.json"))
    for path in kept[:-1]:
        (folder / path.name).write_bytes(path.read_bytes())
    script, log = _stand_in_claude(tmp_path / "bin")
    _env(monkeypatch, script.parent, folder, "replay")
    code = main(
        ["run", CORPUS, "--regulations", "DORA,AI-ACT", "--out", str(tmp_path / "out")],
        loader=loader,
    )
    assert code == 2
    assert "no usable answer" in capsys.readouterr().err
    assert not log.exists() or log.read_text("utf-8") == ""
    assert not (tmp_path / "out" / CORPUS).exists()


# The folder of open recordings a clean clone replays from


def test_the_open_recordings_default_to_the_folder_the_repository_commits():
    from assessment.__main__ import open_recordings

    from utils import PROJECT_ROOT

    assert open_recordings(CORPUS) == (
        PROJECT_ROOT / "data" / "assessments" / CORPUS / "recordings"
    )


def test_a_partial_replay_reads_the_open_recordings_when_no_folder_is_named(
    loader, capsys, monkeypatch, tmp_path, recordings
):
    import assessment.__main__ as cli

    script, log = _stand_in_claude(tmp_path / "bin")
    _env(monkeypatch, script.parent, recordings, "replay")
    monkeypatch.delenv("MODEL_RECORDINGS_DIR")
    monkeypatch.setattr(cli, "open_recordings", lambda corpus: recordings)
    code = main(
        ["run", CORPUS, "--regulations", "DORA,AI-ACT", "--out", str(tmp_path / "out")],
        loader=loader,
    )
    assert code == 0, capsys.readouterr().err
    assert not log.exists() or log.read_text("utf-8") == ""
    assert "MODEL_RECORDINGS_DIR" not in os.environ


def test_a_named_folder_wins_over_the_default(loader, capsys, monkeypatch, tmp_path, recordings):
    import assessment.__main__ as cli

    script, _ = _stand_in_claude(tmp_path / "bin")
    _env(monkeypatch, script.parent, recordings, "replay")
    monkeypatch.setattr(cli, "open_recordings", lambda corpus: tmp_path / "nothing-here")
    code = main(
        ["run", CORPUS, "--regulations", "DORA,AI-ACT", "--out", str(tmp_path / "out")],
        loader=loader,
    )
    assert code == 0, capsys.readouterr().err


def test_a_whole_run_does_not_take_the_open_recordings_as_its_default(
    loader, monkeypatch, tmp_path
):
    import assessment.__main__ as cli

    seen: list[str | None] = []

    def factory():
        seen.append(os.environ.get("MODEL_RECORDINGS_DIR"))
        return ScriptedJudge()

    monkeypatch.setenv("MODEL_BACKEND", "replay")
    monkeypatch.setenv("MODEL_RECORDINGS_DIR", "x")
    monkeypatch.delenv("MODEL_RECORDINGS_DIR")
    monkeypatch.setattr(cli, "open_recordings", lambda corpus: tmp_path / "open")
    main(["run", CORPUS, "--out", str(tmp_path / "out")], judge_factory=factory, loader=loader)
    main(
        ["run", CORPUS, "--regulations", "DORA,AI-ACT", "--out", str(tmp_path / "out2")],
        judge_factory=factory,
        loader=loader,
    )
    assert seen == [None, str(tmp_path / "open")]
    assert "MODEL_RECORDINGS_DIR" not in os.environ
