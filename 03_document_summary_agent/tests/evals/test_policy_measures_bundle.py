"""The measures read a written bundle: the fake bundle's folder, through the command line."""

import json
import re

import pytest
from assessment.bundle import write_bundle
from assessment.fake import build_fake_bundle
from assessment.provisions import resolve_provision
from assessment.texts import load_texts

from evals import policy_measures
from evals.policy_dataset import read_seeds

LINE = re.compile(
    r"^(?:seeded_gaps_found \[(?:DORA|AI Act|SS1/23|all)\]: "
    r"(?:\d+ of \d+ seeded gaps|none in scope)"
    r"|false_gaps \[(?:DORA|AI Act|SS1/23|all)\]: (?:\d+ of \d+ seeds the labels hold as covered"
    r"|none in scope)"
    r"|wrong_citations \[(?:DORA|AI Act|SS1/23|all)\]: "
    r"(?:\d+ of \d+ seeds that name clauses and were found as anything but not covered"
    r"|none in scope)"
    r"|same_state \[(?:DORA|AI Act|SS1/23|all)\]: (?:\d+ of \d+ seeds|none in scope))$"
)
LABELS = {"DORA": "DORA", "AI-ACT": "AI Act", "SS1-23": "SS1/23"}


def _no_network(address, headers):
    raise OSError(f"no network call in a test ({address})")


@pytest.fixture(scope="module")
def fake():
    return build_fake_bundle(load_texts("harbour-mutual-bank", opener=_no_network))


@pytest.fixture()
def folder(fake, tmp_path):
    return write_bundle(fake, tmp_path)


def test_the_fake_bundles_matches_are_measured_over_all_55_seeds(fake, folder, capsys):
    assert policy_measures.main([str(folder)]) == 0
    out = capsys.readouterr().out.splitlines()
    measure_lines = [line for line in out if "[" in line]
    assert len(measure_lines) == 16
    assert all(LINE.match(line) for line in measure_lines), measure_lines
    assert f"seeds with no match: {55 - len(fake.seed_matches)} of 55" in "\n".join(out)


def test_the_printed_figures_are_the_ones_the_bundles_matches_give(fake, folder, capsys):
    policy_measures.main([str(folder)])
    out = capsys.readouterr().out
    seeds = {s.seed_id: s for s in read_seeds()}
    for key, label in LABELS.items():
        mine = [m for m in fake.seed_matches if m.regulation == key]
        gaps_in_file = sum(
            1 for s in seeds.values() if s.regulation == key and s.state != "covered"
        )
        found = sum(
            1 for m in mine if seeds[m.seed_id].state != "covered" and m.found_state != "covered"
        )
        assert f"seeded_gaps_found [{label}]: {found} of {gaps_in_file} seeded gaps" in out
        same = sum(1 for m in mine if m.found_state == seeds[m.seed_id].state)
        total = sum(1 for s in seeds.values() if s.regulation == key)
        assert f"same_state [{label}]: {same} of {total} seeds" in out


def test_a_fake_run_may_leave_seeds_unmatched_and_a_recorded_run_may_not(fake, tmp_path, capsys):
    folder = write_bundle(fake, tmp_path)
    assert policy_measures.main([str(folder)]) == 0
    index = json.loads((folder / "bundle.json").read_text("utf-8"))
    index["run"] = "record"
    (folder / "bundle.json").write_text(json.dumps(index), "utf-8")
    capsys.readouterr()
    assert policy_measures.main([str(folder)]) == 1
    assert "seeds with no match" in capsys.readouterr().out


def test_require_all_fails_a_file_that_leaves_a_seed_unmatched(folder, capsys):
    matches = folder / "seed_matches.jsonl"
    assert policy_measures.main(["--seed-matches", str(matches)]) == 0
    assert policy_measures.main(["--seed-matches", str(matches), "--require-all"]) == 1


def test_a_folder_without_a_bundle_index_is_refused_naming_it(tmp_path, capsys):
    assert policy_measures.main([str(tmp_path)]) == 2
    assert "bundle.json" in capsys.readouterr().err


def test_a_match_edited_to_a_different_seeded_state_stops_the_run(folder, capsys):
    path = folder / "seed_matches.jsonl"
    lines = path.read_text("utf-8").splitlines()
    lines[0] = lines[0].replace('"seeded_state": "', '"seeded_state": "x', 1)
    path.write_text("\n".join(lines) + "\n", "utf-8")
    assert policy_measures.main(["--seed-matches", str(path)]) == 2
    assert "seeded_state" in capsys.readouterr().err


def test_a_command_line_with_no_source_is_refused(capsys):
    with pytest.raises(SystemExit) as stop:
        policy_measures.main([])
    assert stop.value.code == 2
    assert "give a bundle folder" in capsys.readouterr().err


def _full_rows(*, leave_out=()):
    """Rows for every seed that a run could have written, each placed where its provision is."""
    rows = []
    for seed in read_seeds():
        if seed.seed_id in leave_out:
            continue
        place = resolve_provision(seed.regulation, seed.provision)
        clauses = [{"document": d, "clause": c} for d, c in seed.clauses]
        rows.append(
            {
                "seed_id": seed.seed_id,
                "regulation": seed.regulation,
                "target": place.anchor,
                "points": list(place.points),
                "obligation_ids": [f"{seed.regulation} {place.anchor}"],
                "found_state": seed.state,
                "seeded_state": seed.state,
                "cited_clauses": [] if seed.state == "not covered" else clauses,
                "seeded_clauses": clauses,
            }
        )
    return rows


def _write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_a_complete_and_correctly_placed_file_passes_under_require_all(tmp_path, capsys):
    path = _write(tmp_path / "seed_matches.jsonl", _full_rows())
    assert policy_measures.main(["--seed-matches", str(path), "--require-all"]) == 0
    assert "seeds with no match" not in capsys.readouterr().out


def test_a_covered_seed_with_no_match_fails_under_require_all_and_is_named(tmp_path, capsys):
    path = _write(tmp_path / "seed_matches.jsonl", _full_rows(leave_out={"AIA-01"}))
    assert policy_measures.main(["--seed-matches", str(path)]) == 0
    capsys.readouterr()
    assert policy_measures.main(["--seed-matches", str(path), "--require-all"]) == 1
    out = capsys.readouterr().out
    assert "seeds with no match: 1 of 55 (AIA-01)" in out


def test_a_seed_matched_to_the_assessment_of_another_obligation_stops_the_run(tmp_path, capsys):
    rows = _full_rows()
    row = next(r for r in rows if r["seed_id"] == "DORA-22")
    assert row["target"] == "art:30/2"
    row["target"] = "art:30/3"
    path = _write(tmp_path / "seed_matches.jsonl", rows)
    assert policy_measures.main(["--seed-matches", str(path)]) == 2
    err = capsys.readouterr().err
    assert "DORA-22" in err and "art:30/3" in err and "art:30/2" in err


def test_a_seed_matched_at_the_wrong_point_stops_the_run(tmp_path, capsys):
    rows = _full_rows()
    next(r for r in rows if r["seed_id"] == "DORA-22")["points"] = ["f"]
    path = _write(tmp_path / "seed_matches.jsonl", rows)
    assert policy_measures.main(["--seed-matches", str(path), "--require-all"]) == 2
    assert "DORA-22" in capsys.readouterr().err


def test_a_folder_whose_index_names_no_run_is_held_to_every_seed(fake, tmp_path, capsys):
    folder = write_bundle(fake, tmp_path)
    index = json.loads((folder / "bundle.json").read_text("utf-8"))
    assert index["run"] == "fake"
    del index["run"]
    (folder / "bundle.json").write_text(json.dumps(index), "utf-8")
    assert policy_measures.main([str(folder)]) == 1
    assert "seeds with no match" in capsys.readouterr().out
