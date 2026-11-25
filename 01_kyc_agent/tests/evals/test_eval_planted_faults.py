"""Every planted fault is caught by the measures it is meant to move, and by no others."""

import copy

import pytest

from evals import evaluators as ev
from evals import planted_faults as pf
from evals.labels import read_labels

EXPECTED = {
    "wrong_risk_on_a_held_application": ["risk_agrees"],
    "wrong_decision_on_a_held_application": ["decision_agrees"],
    "wrong_settled_proposal": ["risk_agrees", "settled_agree"],
    "edge_case_settled_by_the_checks": [
        "edge_cases_sent",
        "sent_to_person",
        "settled_agree",
        "settled_by_checks",
    ],
    "starter_rule_blinded": ["starter_decision_agrees", "starter_risk_agrees"],
    "screening_dropped": ["screenings_accounted"],
    "application_dropped": ["applications_accounted"],
}


@pytest.fixture(scope="module")
def results():
    return pf.run_plants(pf.PLANTS)


def test_there_is_one_plant_for_each_expected_fault():
    assert [p.name for p in pf.PLANTS] == list(EXPECTED)


def test_every_plant_is_caught(results):
    assert all(r.caught for r in results), [r.line() for r in results if not r.caught]


@pytest.mark.parametrize("name", list(EXPECTED))
def test_each_plant_moves_its_declared_measures_and_no_others(results, name):
    result = next(r for r in results if r.name == name)
    assert result.moved == sorted(EXPECTED[name])


def test_every_measure_is_moved_by_at_least_one_plant(results):
    assert {key for r in results for key in r.moved} == set(ev.MEASURE_KEYS)


def test_the_baseline_agrees_with_every_label_and_the_starters_rule_with_22_of_25():
    totals = pf.totals_of(pf.baseline_outputs())
    for key in ("risk_agrees", "decision_agrees", "settled_agree", "edge_cases_sent"):
        assert totals[key][0] == totals[key][1], key
    assert totals["applications_accounted"] == (25, 25)
    assert totals["screenings_accounted"] == (350, 350)
    assert totals["starter_risk_agrees"] == (22, 25)


def test_the_baseline_profiles_are_written_in_their_applications():
    from utils import db

    texts = {r["customer_id"]: r["application"] for r in db.table("applications")}
    for customer_id, profile in pf.read_profiles().items():
        assert profile["full_name"] in texts[customer_id], customer_id
    assert len(pf.read_profiles()) == 25


def test_the_baseline_is_built_from_the_labels():
    outputs = pf.baseline_outputs()
    for label in read_labels():
        assert outputs[label.customer_id]["risk_level"] == label.risk_level
        assert outputs[label.customer_id]["settled"] is (not label.edge_case)


def test_a_plant_that_changes_nothing_is_missed():
    nothing = pf.Plant("nothing", "changes nothing", ("risk_agrees",), lambda o: copy.deepcopy(o))
    [result] = pf.run_plants([nothing])
    assert not result.caught
    assert result.line().startswith("MISSED nothing")


def test_a_plant_that_moves_a_measure_it_did_not_declare_is_missed():
    too_narrow = pf.Plant(
        "too_narrow", "a wrong settled proposal declared as one measure", ("risk_agrees",),
        pf.PLANTS[2].apply,
    )  # fmt: skip
    [result] = pf.run_plants([too_narrow])
    assert not result.caught
    assert "settled_agree" in result.line()


def test_a_blinded_evaluator_lets_its_plant_through(monkeypatch):
    real = ev.evaluate_pair

    def blind(example, output):
        measures = real(example, output)
        return [
            ev.Measure("risk_agrees", 1, 1, ev.APPLICATIONS) if m.key == "risk_agrees" else m
            for m in measures
        ]

    monkeypatch.setattr(pf, "evaluate_pair", blind)
    [result] = pf.run_plants([pf.PLANTS[0]])
    assert not result.caught


def test_main_prints_one_line_per_plant_and_exits_zero_when_all_are_caught(capsys):
    assert pf.main() == 0
    out = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in out[:-1]] == ["CAUGHT"] * 7
    assert out[-1] == "7 of 7 plants caught"


def test_main_exits_non_zero_when_any_plant_is_missed(monkeypatch, capsys):
    nothing = pf.Plant("nothing", "x", ("risk_agrees",), lambda o: copy.deepcopy(o))
    monkeypatch.setattr(pf, "PLANTS", (*pf.PLANTS, nothing))
    assert pf.main() == 1
    assert "MISSED nothing" in capsys.readouterr().out
