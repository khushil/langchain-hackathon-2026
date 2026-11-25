"""Each policy measure has a planted fault that makes its figure fall."""

import dataclasses

import pytest

from evals import policy_measures
from evals.policy_dataset import read_seeds
from evals.policy_measures import (
    MEASURES,
    PLANTS,
    PlantResult,
    count_of,
    measure_seeds,
    perfect_matches,
    run_plants,
)


@pytest.fixture(scope="module")
def seeds():
    return read_seeds()


def test_perfect_matches_score_in_full_on_every_measure(seeds):
    report = measure_seeds(seeds, perfect_matches(seeds))
    full = {
        measure: (
            count_of(report, measure, "all").numerator,
            count_of(report, measure, "all").denominator,
        )
        for measure in MEASURES
    }
    assert full["seeded_gaps_found"] == (23, 23)
    assert full["same_state"] == (55, 55)
    assert full["false_gaps"] == (0, 32)
    assert full["wrong_citations"][0] == 0 and full["wrong_citations"][1] > 0
    assert report.unmatched == () and report.uncompared == ()


def test_every_measure_has_at_least_one_plant_that_declares_it(seeds):
    declared = {m for plant in PLANTS for m in plant.degrades}
    assert declared == set(MEASURES)


def test_each_plant_is_caught_by_exactly_the_measures_it_declares(seeds):
    results = run_plants(seeds)
    assert [r.name for r in results] == [p.name for p in PLANTS]
    assert all(r.caught for r in results), [r.line() for r in results if not r.caught]
    for result, plant in zip(results, PLANTS, strict=True):
        assert result.degraded == list(plant.degrades)


@pytest.mark.parametrize("plant", PLANTS, ids=lambda p: p.name)
def test_a_plant_lowers_its_measures_for_the_regulation_it_touches_and_for_all(seeds, plant):
    clean = measure_seeds(seeds, perfect_matches(seeds))
    planted = measure_seeds(seeds, plant.apply(seeds, perfect_matches(seeds)))
    for measure in plant.degrades:
        moved = [
            scope
            for scope in ("DORA", "AI-ACT", "SS1-23", "all")
            if count_of(planted, measure, scope).numerator
            != count_of(clean, measure, scope).numerator
        ]
        assert "all" in moved and len(moved) == 2, (plant.name, measure, moved)


@pytest.mark.parametrize("plant", PLANTS, ids=lambda p: p.name)
def test_a_plant_leaves_the_other_measures_numerators_as_they_were(seeds, plant):
    clean = measure_seeds(seeds, perfect_matches(seeds))
    planted = measure_seeds(seeds, plant.apply(seeds, perfect_matches(seeds)))
    for measure in set(MEASURES) - set(plant.degrades):
        for scope in ("DORA", "AI-ACT", "SS1-23", "all"):
            assert (
                count_of(planted, measure, scope).numerator
                == count_of(clean, measure, scope).numerator
            ), (plant.name, measure, scope)


def test_the_dropped_match_plant_leaves_the_seed_listed_as_unmatched(seeds):
    plant = next(p for p in PLANTS if p.name == "match-dropped")
    report = measure_seeds(seeds, plant.apply(seeds, perfect_matches(seeds)))
    assert len(report.unmatched) == 1


@pytest.mark.parametrize("measure", MEASURES)
def test_a_measure_that_stops_counting_leaves_its_plants_missed(seeds, measure, monkeypatch):
    real = policy_measures.measure_seeds

    def broken(seed_list, matches):
        report = real(seed_list, matches)
        counts = tuple(
            dataclasses.replace(c, numerator=0) if c.measure == measure else c
            for c in report.counts
        )
        return dataclasses.replace(report, counts=counts)

    monkeypatch.setattr(policy_measures, "measure_seeds", broken)
    missed = [r.name for r in run_plants(seeds) if not r.caught]
    declared = [p.name for p in PLANTS if measure in p.degrades]
    assert missed
    assert set(declared) <= set(missed)


def test_a_plant_that_changes_nothing_is_reported_missed(seeds):
    idle = dataclasses.replace(PLANTS[0], name="idle", apply=lambda s, matches: matches)
    (result,) = run_plants(seeds, plants=(idle,))
    assert isinstance(result, PlantResult)
    assert not result.caught
    assert result.line().startswith("MISSED idle:") and "nothing fell" in result.line()


def test_a_caught_plant_prints_the_measures_that_fell(seeds):
    result = run_plants(seeds, plants=(PLANTS[0],))[0]
    assert result.line().startswith(f"CAUGHT {PLANTS[0].name}: ")
    assert ", ".join(PLANTS[0].degrades) in result.line()


def test_the_self_test_prints_one_line_per_plant_and_exits_zero(capsys):
    assert policy_measures.main(["--selftest"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len([line for line in lines if line.startswith("CAUGHT ")]) == len(PLANTS)
    assert not [line for line in lines if line.startswith("MISSED")]
    assert lines[-1] == f"planted faults caught: {len(PLANTS)} of {len(PLANTS)}"


def test_the_self_test_exits_non_zero_when_a_plant_is_missed(monkeypatch, capsys):
    idle = dataclasses.replace(PLANTS[0], apply=lambda s, matches: matches)
    monkeypatch.setattr(policy_measures, "PLANTS", (idle,))
    assert policy_measures.main(["--selftest"]) == 1
    out = capsys.readouterr().out
    assert "MISSED" in out and out.splitlines()[-1] == "planted faults caught: 0 of 1"
