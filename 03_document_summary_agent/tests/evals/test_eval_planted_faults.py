"""Tests that every planted fault is caught by exactly the measures it is meant to move."""

import copy

import pytest
from evals import evaluators as ev
from evals import planted_faults as pf
from evals.build_dataset import read_examples

EXPECTED = {
    "paraphrased_quote": ["quotes_word_for_word"],
    "converted_deadline": ["deadlines_as_written", "deadlines_matched"],
    "invented_obligation": ["invented_obligations", "paragraph_precision"],
    "dropped_obligation": ["obligations_found"],
    "dropped_deadline": ["deadlines_matched"],
    "lost_paragraph": ["obligations_found", "paragraph_recall"],
}


@pytest.fixture(scope="module")
def results():
    return pf.run_plants(pf.PLANTS)


def test_there_is_one_plant_per_expected_fault():
    assert [p.name for p in pf.PLANTS] == list(EXPECTED)


def test_every_plant_is_caught(results):
    assert [r.name for r in results] == list(EXPECTED)
    assert all(r.caught for r in results), [r.line() for r in results if not r.caught]


@pytest.mark.parametrize("name", list(EXPECTED))
def test_each_plant_degrades_exactly_its_declared_measures(results, name):
    result = next(r for r in results if r.name == name)
    assert result.degraded == sorted(EXPECTED[name])


def test_every_measure_is_moved_by_at_least_one_plant(results):
    moved = {key for r in results for key in r.degraded}
    assert moved == set(ev.MEASURE_KEYS)


def test_the_baseline_the_plants_start_from_is_full_on_every_measure():
    sections = read_examples("sections.jsonl")
    for example in sections:
        scored = ev.score_summary(pf.baseline_summary(example), example["reference_outputs"])
        assert all(m.is_full or not m.in_scope for m in scored)


def test_a_plant_that_changes_nothing_is_missed():
    do_nothing = pf.Plant(
        name="nothing",
        description="changes nothing",
        level="section",
        degrades=("quotes_word_for_word",),
        apply=lambda summary: copy.deepcopy(summary),
    )
    [result] = pf.run_plants([do_nothing])
    assert not result.caught
    assert result.line().startswith("MISSED nothing")


def test_a_plant_that_moves_a_measure_it_did_not_declare_is_missed():
    too_wide = pf.Plant(
        name="too_wide",
        description="lost paragraph but declared as one measure",
        level="section",
        degrades=("obligations_found",),
        apply=pf.PLANTS[-1].apply,
    )
    [result] = pf.run_plants([too_wide])
    assert not result.caught
    assert "paragraph_recall" in result.line()


def test_a_blinded_evaluator_lets_its_plant_through(monkeypatch):
    monkeypatch.setitem(
        ev._MEASURES,
        "quotes_word_for_word",
        lambda scene: ev.Measure(
            "quotes_word_for_word", 1, 1, "predicted obligations citing a paragraph in scope"
        ),
    )
    [result] = pf.run_plants([pf.PLANTS[0]])
    assert not result.caught


def test_main_prints_one_line_per_plant_and_exits_zero_when_all_are_caught(capsys):
    assert pf.main() == 0
    out = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in out[:-1]] == ["CAUGHT"] * 6
    assert out[-1] == "6 of 6 plants caught"


def test_main_exits_non_zero_when_any_plant_is_missed(monkeypatch, capsys):
    do_nothing = pf.Plant(
        "nothing", "x", "section", ("quotes_word_for_word",), lambda s: copy.deepcopy(s)
    )
    monkeypatch.setattr(pf, "PLANTS", (*pf.PLANTS, do_nothing))
    assert pf.main() == 1
    out = capsys.readouterr().out
    assert "MISSED nothing" in out
    assert out.strip().splitlines()[-1] == "6 of 7 plants caught"
