"""Every planted fault is caught by exactly the measures it is meant to move."""

import copy

import pytest

from evals import evaluators as ev
from evals import planted_faults as pf
from evals.build_dataset import read_examples

EXPECTED = {
    "approved_a_block": ["blocks_found", "decisions_agree"],
    "blocked_an_approval": ["decisions_agree", "false_blocks"],
    "score_far_off": ["scores_in_band"],
    "ambiguous_not_flagged": ["ambiguous_flagged"],
    "clear_flagged": ["clear_not_flagged"],
    "dropped_assessment": ["assessed", "clear_not_flagged", "decisions_agree", "scores_in_band"],
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
    assert {key for r in results for key in r.degraded} == set(ev.MEASURE_KEYS)


def test_the_baseline_the_plants_start_from_is_full_on_every_measure():
    for example in read_examples():
        for measure in ev.evaluate_pair(example, pf.baseline(example)):
            assert measure.is_full or not measure.in_scope


def test_a_plant_that_changes_nothing_is_missed():
    nothing = pf.Plant(
        "nothing", "changes nothing", ("decisions_agree",), lambda a: copy.deepcopy(a)
    )
    result = pf.run_plants([nothing])[0]
    assert not result.caught and "MISSED" in result.line()


def test_a_plant_that_moves_a_measure_it_did_not_declare_is_missed():
    wide = pf.Plant("wide", "moves too much", ("assessed",), lambda a: [])
    result = pf.run_plants([wide])[0]
    assert not result.caught and result.degraded != ["assessed"]


def test_the_command_prints_one_line_each_and_exits_zero_when_all_are_caught(capsys):
    assert pf.main() == 0
    out = capsys.readouterr().out
    assert out.count("CAUGHT") == 6 and "6 of 6 plants caught" in out
