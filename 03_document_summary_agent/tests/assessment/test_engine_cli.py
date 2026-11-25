"""The command line: ``plan`` counts before any call, ``run`` writes the bundle, prints lines."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from assessment.__main__ import main
from assessment.bundle import read_bundle
from assessment.run_lines import run_lines
from assessment_fakes import AlwaysBadJudge, ScriptedJudge

from utils import PROJECT_ROOT

CORPUS = "harbour-mutual-bank"
WRONG_POPULATION = "seeds that name clauses and were found as anything but not covered"


@pytest.fixture
def loader(texts):
    return lambda corpus: texts


def _never():
    raise AssertionError("a judge was made before the plan was printed")


def test_plan_prints_the_call_count_and_makes_no_judge(loader, capsys, monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "replay")
    code = main(["plan", CORPUS], judge_factory=_never, loader=loader)
    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out[0].startswith("Plan: 219 applicable obligations, 219 judgement calls")
    assert "DORA 101" in out[1] and "AI Act 21" in out[1] and "SS1/23 97" in out[1]


def test_run_prints_the_plan_first_then_the_lines_the_deck_reads(
    loader, capsys, monkeypatch, tmp_path
):
    monkeypatch.setenv("MODEL_BACKEND", "record")
    code = main(
        ["run", CORPUS, "--out", str(tmp_path)],
        judge_factory=lambda: ScriptedJudge(),
        loader=loader,
    )
    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out[0].startswith("Plan: ")
    patterns = [
        r"^Document graph: \d+ documents, \d+ links$",
        r"^Obligation register: 738 obligations, 219 apply to the firm$",
        r"^Assessments: 219 applicable obligations assessed: \d+ covered, \d+ partly covered, "
        r"\d+ not covered, \d+ in conflict$",
        r"^seeded_gaps_found \[DORA\]: \d+ of 12 seeded gaps$",
        r"^seeded_gaps_found \[AI Act\]: \d+ of 5 seeded gaps$",
        r"^seeded_gaps_found \[SS1/23\]: \d+ of 6 seeded gaps$",
        r"^seeded_gaps_found \[all\]: \d+ of 23 seeded gaps$",
        r"^false_gaps \[DORA\]: \d+ of 13 seeds the labels hold as covered$",
        r"^false_gaps \[AI Act\]: \d+ of 7 seeds the labels hold as covered$",
        r"^false_gaps \[SS1/23\]: \d+ of 12 seeds the labels hold as covered$",
        r"^false_gaps \[all\]: \d+ of 32 seeds the labels hold as covered$",
        rf"^wrong_citations \[DORA\]: \d+ of \d+ {WRONG_POPULATION}$",
        rf"^wrong_citations \[AI Act\]: \d+ of \d+ {WRONG_POPULATION}$",
        rf"^wrong_citations \[SS1/23\]: \d+ of \d+ {WRONG_POPULATION}$",
        rf"^wrong_citations \[all\]: \d+ of \d+ {WRONG_POPULATION}$",
    ]
    for pattern in patterns:
        assert sum(bool(re.match(pattern, line)) for line in out) == 1, pattern
    assert read_bundle(tmp_path / CORPUS).index.run == "record"


def test_the_example_assessment_line_has_six_fields_and_no_digit_in_its_quotes(
    loader, capsys, monkeypatch, tmp_path
):
    monkeypatch.setenv("MODEL_BACKEND", "record")
    main(
        ["run", CORPUS, "--out", str(tmp_path)],
        judge_factory=lambda: ScriptedJudge(),
        loader=loader,
    )
    line = next(
        x for x in capsys.readouterr().out.splitlines() if x.startswith("Example assessment: ")
    )
    fields = line.removeprefix("Example assessment: ").split(" | ")
    assert len(fields) == 6
    assert fields[2] in ("not covered", "partly covered")
    assert not re.search(r"\d", fields[3]) and not re.search(r"\d", fields[5])


def test_the_run_label_follows_the_model_backend(loader, capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_BACKEND", "replay")
    main(
        ["run", CORPUS, "--out", str(tmp_path)],
        judge_factory=lambda: ScriptedJudge(),
        loader=loader,
    )
    assert read_bundle(tmp_path / CORPUS).index.run == "replay"


def test_a_live_backend_is_refused_because_a_recording_would_not_be_labelled_as_one(
    loader, capsys, monkeypatch, tmp_path
):
    monkeypatch.setenv("MODEL_BACKEND", "claude-code")
    code = main(["run", CORPUS, "--out", str(tmp_path)], judge_factory=_never, loader=loader)
    assert code == 2
    assert "MODEL_BACKEND" in capsys.readouterr().err
    assert not (tmp_path / CORPUS).exists()


def test_a_refused_judgement_exits_2_names_the_obligation_and_writes_nothing(
    loader, capsys, monkeypatch, tmp_path
):
    monkeypatch.setenv("MODEL_BACKEND", "record")
    code = main(
        ["run", CORPUS, "--out", str(tmp_path)],
        judge_factory=lambda: AlwaysBadJudge(mixed=False),
        loader=loader,
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "no usable answer" in captured.err and "DORA art:" in captured.err
    assert not (tmp_path / CORPUS).exists()


def test_a_bundle_that_fails_a_check_exits_2_and_writes_nothing(
    loader, capsys, monkeypatch, tmp_path
):
    from assessment import engine

    monkeypatch.setenv("MODEL_BACKEND", "record")
    monkeypatch.setattr(engine, "_clause_map", lambda prepared, assessments: [])
    code = main(
        ["run", CORPUS, "--out", str(tmp_path)],
        judge_factory=lambda: ScriptedJudge(mixed=False),
        loader=loader,
    )
    assert code == 2
    assert "clause" in capsys.readouterr().err
    assert not (tmp_path / CORPUS).exists()


def test_a_write_that_fails_partway_leaves_the_folder_as_it_was(
    loader, capsys, monkeypatch, tmp_path
):
    from assessment import __main__ as command
    from assessment.bundle import write_bundle

    monkeypatch.setenv("MODEL_BACKEND", "record")
    folder = tmp_path / CORPUS
    (folder / "recordings").mkdir(parents=True)
    (folder / "recordings" / "kept.json").write_text("{}", "utf-8")
    (folder / "bundle.json").write_text("older bundle", "utf-8")

    def breaks_after_writing(bundle, root):
        write_bundle(bundle, root)
        raise OSError("no space left on device")

    monkeypatch.setattr(command, "write_bundle", breaks_after_writing)
    code = main(
        ["run", CORPUS, "--out", str(tmp_path)],
        judge_factory=lambda: ScriptedJudge(mixed=False),
        loader=loader,
    )
    assert code == 2
    assert "no space left" in capsys.readouterr().err
    assert (folder / "bundle.json").read_text("utf-8") == "older bundle"
    assert sorted(p.name for p in folder.iterdir()) == ["bundle.json", "recordings"]
    assert (folder / "recordings" / "kept.json").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [CORPUS]


def test_a_run_over_an_existing_folder_replaces_its_bundle_and_keeps_what_else_is_there(
    loader, capsys, monkeypatch, tmp_path
):
    monkeypatch.setenv("MODEL_BACKEND", "record")
    folder = tmp_path / CORPUS
    (folder / "recordings").mkdir(parents=True)
    (folder / "recordings" / "kept.json").write_text("{}", "utf-8")
    (folder / "bundle.json").write_text("older bundle", "utf-8")
    code = main(
        ["run", CORPUS, "--out", str(tmp_path)],
        judge_factory=lambda: ScriptedJudge(mixed=False),
        loader=loader,
    )
    assert code == 0
    assert read_bundle(folder).index.run == "record"
    assert (folder / "recordings" / "kept.json").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [CORPUS]


def test_an_unknown_corpus_exits_2_and_names_it(capsys, monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "replay")
    code = main(["plan", "no-such-corpus"], judge_factory=_never)
    assert code == 2
    assert "no-such-corpus" in capsys.readouterr().err


def test_run_lines_change_when_a_found_state_changes(loader, texts):
    from assessment.engine import prepare, run_assessment
    from assessment.profile import load_profile

    bundle = run_assessment(
        CORPUS,
        ScriptedJudge(),
        texts=texts,
        prepared=prepare(texts, load_profile(CORPUS)),
        run="record",
    )
    before = run_lines(bundle, texts)
    flipped = [
        m.model_copy(
            update={"found_state": "covered" if m.found_state != "covered" else "not covered"}
        )
        for m in bundle.seed_matches
    ]
    after = run_lines(bundle.model_copy(update={"seed_matches": flipped}), texts)
    assert before != after
    assert before[0] == after[0]


def test_the_module_runs_as_a_program_and_prints_the_plan():
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(PROJECT_ROOT), str(PROJECT_ROOT.parent / "fsi_common")]),
        "MODEL_BACKEND": "replay",
    }
    done = subprocess.run(
        [sys.executable, "-m", "assessment", "plan", CORPUS],
        cwd=Path(PROJECT_ROOT),
        env={k: v for k, v in env.items() if k != "PYTHONHOME"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines()[0].startswith("Plan: 219 applicable obligations")


def test_run_lines_count_what_the_seed_matches_say(texts):
    from assessment.engine import prepare, run_assessment
    from assessment.profile import load_profile

    bundle = run_assessment(
        CORPUS,
        ScriptedJudge(),
        texts=texts,
        prepared=prepare(texts, load_profile(CORPUS)),
        run="record",
    )
    lines = run_lines(bundle, texts)
    for key, name in (("DORA", "DORA"), ("AI-ACT", "AI Act"), ("SS1-23", "SS1/23")):
        group = [m for m in bundle.seed_matches if m.regulation == key]
        gaps = [m for m in group if m.seeded_state != "covered"]
        covered = [m for m in group if m.seeded_state == "covered"]
        citing = [m for m in group if m.seeded_clauses and m.found_state != "not covered"]
        wrong = [
            m
            for m in citing
            if not {(c.document, c.clause) for c in m.cited_clauses}
            & {(c.document, c.clause) for c in m.seeded_clauses}
        ]
        found = sum(m.found_state != "covered" for m in gaps)
        false = sum(m.found_state != "covered" for m in covered)
        assert f"seeded_gaps_found [{name}]: {found} of {len(gaps)} seeded gaps" in lines
        assert (
            f"false_gaps [{name}]: {false} of {len(covered)} seeds the labels hold as covered"
            in lines
        )
        assert (
            f"wrong_citations [{name}]: {len(wrong)} of {len(citing)} seeds that name clauses "
            "and were found as anything but not covered" in lines
        )
