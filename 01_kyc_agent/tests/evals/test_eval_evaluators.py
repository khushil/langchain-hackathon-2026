"""The measures, each a count over a stated population, on synthetic outputs and on a real run."""

import pytest

from evals import evaluators as ev
from evals.build_dataset import read_examples
from evals.labels import read_labels
from fsi_common.evals.runner import run_evaluators


def example(customer_id="CUST-001", risk="low", edge=False):
    return {
        "key": customer_id,
        "inputs": {"customer_id": customer_id},
        "reference_outputs": {
            "risk_level": risk,
            "decision": "reject" if risk == "high" else "approve",
            "application": "x",
            "label_reason": "Edge case: x" if edge else "Clean customer",
            "edge_case": edge,
        },
    }


def output(**changes):
    base = {
        "customer_id": "CUST-001",
        "risk_level": "low",
        "decision": "approve",
        "settled": True,
        "profile": {"full_name": "Sarah Mitchell", "date_of_birth": "1990-03-14"},
        "accounting": {"applications": [1, 1], "screenings": [14, 14]},
    }
    return {**base, **changes}


def by_key(measures):
    return {m.key: m for m in measures}


def test_there_are_ten_measures_named_in_one_place():
    assert len(ev.MEASURE_KEYS) == 10
    assert [m.key for m in ev.evaluate_pair(example(), output())] == list(ev.MEASURE_KEYS)


def test_an_agreeing_settled_application_scores_in_every_agreement_measure():
    m = by_key(ev.evaluate_pair(example(), output()))
    for key in ("risk_agrees", "decision_agrees", "settled_by_checks", "settled_agree"):
        assert (m[key].numerator, m[key].denominator) == (1, 1), key
    assert (m["sent_to_person"].numerator, m["sent_to_person"].denominator) == (0, 1)
    assert m["edge_cases_sent"].denominator == 0
    assert not m["edge_cases_sent"].in_scope


def test_a_proposal_that_disagrees_with_the_label_scores_nothing_in_agreement():
    m = by_key(ev.evaluate_pair(example(), output(risk_level="high", decision="reject")))
    assert (m["risk_agrees"].numerator, m["decision_agrees"].numerator) == (0, 0)
    assert (m["settled_agree"].numerator, m["settled_agree"].denominator) == (0, 1)


def test_a_settled_proposal_agrees_only_when_the_level_and_the_decision_both_do():
    m = by_key(ev.evaluate_pair(example(), output(decision="reject")))
    assert (m["risk_agrees"].numerator, m["decision_agrees"].numerator) == (1, 0)
    assert m["settled_agree"].numerator == 0


def test_an_unsent_application_is_out_of_the_settled_agreement_population():
    m = by_key(
        ev.evaluate_pair(example(), output(settled=False, risk_level="high", decision="reject"))
    )
    assert (m["sent_to_person"].numerator, m["sent_to_person"].denominator) == (1, 1)
    assert (m["settled_agree"].numerator, m["settled_agree"].denominator) == (0, 0)


def test_an_edge_case_counts_when_it_was_sent_to_a_person():
    ref = example("CUST-018", risk="low", edge=True)
    sent = by_key(ev.evaluate_pair(ref, output(customer_id="CUST-018", settled=False)))
    kept = by_key(ev.evaluate_pair(ref, output(customer_id="CUST-018", settled=True)))
    assert (sent["edge_cases_sent"].numerator, sent["edge_cases_sent"].denominator) == (1, 1)
    assert (kept["edge_cases_sent"].numerator, kept["edge_cases_sent"].denominator) == (0, 1)


def test_the_starters_rule_is_applied_to_the_name_and_date_of_birth_alone():
    assert ev.starter_rule("Viktor Harlan", "1968-07-02") == ("high", "reject")
    assert ev.starter_rule("Sarah Mitchell", "1990-03-14") == ("low", "approve")
    assert ev.starter_rule("Ivana Strahov", "1996-03-14") == ("high", "reject")


def test_the_starters_rule_is_scored_beside_the_engines():
    ref = example("CUST-002", risk="high")
    out = output(
        customer_id="CUST-002",
        risk_level="high",
        decision="reject",
        profile={"full_name": "Viktor Harlan", "date_of_birth": "1968-07-02"},
    )
    m = by_key(ev.evaluate_pair(ref, out))
    assert (m["starter_risk_agrees"].numerator, m["starter_decision_agrees"].numerator) == (1, 1)
    blind = by_key(
        ev.evaluate_pair(ref, {**out, "profile": {"full_name": None, "date_of_birth": None}})
    )
    assert blind["starter_risk_agrees"].numerator == 0


def test_accounting_is_counted_over_applications_and_screenings():
    m = by_key(
        ev.evaluate_pair(
            example(), output(accounting={"applications": [1, 1], "screenings": [13, 14]})
        )
    )
    assert (m["applications_accounted"].numerator, m["applications_accounted"].denominator) == (
        1,
        1,
    )
    assert (m["screenings_accounted"].numerator, m["screenings_accounted"].denominator) == (13, 14)


def test_an_output_that_is_not_the_expected_shape_is_refused_by_name():
    with pytest.raises(ev.MalformedOutputError, match="risk_level"):
        ev.evaluate_pair(example(), {"customer_id": "CUST-001"})


def test_the_evaluators_are_named_after_their_measures_for_langsmith():
    names = [f.__name__ for f in ev.langsmith_evaluators()]
    assert names == list(ev.MEASURE_KEYS)
    result = ev.langsmith_evaluators()[0](output(), example()["reference_outputs"])
    assert result["key"] == "risk_agrees" and result["score"] == 1.0


def test_a_measure_with_nothing_in_scope_has_no_score_in_langsmith():
    evaluator = next(f for f in ev.langsmith_evaluators() if f.__name__ == "edge_cases_sent")
    result = evaluator(output(), example()["reference_outputs"])
    assert result["score"] is None and "none in scope" in result["comment"]


# On the scripted reader: what the engine does with the starter's 25 applications.


@pytest.fixture(scope="module")
def report():
    from kyc_fakes import ScriptedReader

    from evals.engine_outputs import run_engine

    outputs = run_engine(ScriptedReader())
    pairs = [(e, outputs[e["key"]]) for e in read_examples()]
    return run_evaluators(pairs, [ev.evaluate_pair], required=ev.MEASURE_KEYS), outputs


def totals(report):
    return {m.key: (m.numerator, m.denominator) for m in report.totals}


def test_the_run_is_scored_over_all_25_applications(report):
    run, outputs = report
    assert run.ok, run.failures
    assert len(run.per_example) == len(outputs) == 25


def test_thirteen_are_settled_by_the_checks_and_twelve_go_to_a_person(report):
    t = totals(report[0])
    assert t["settled_by_checks"] == (13, 25)
    assert t["sent_to_person"] == (12, 25)


def test_every_settled_proposal_agrees_with_the_starters_label(report):
    from context.proposals import SETTLED_MATCH_RATE

    matched, population = totals(report[0])["settled_agree"]
    assert (matched, population) == (SETTLED_MATCH_RATE.matched, SETTLED_MATCH_RATE.population)


def test_the_three_edge_cases_are_all_sent_to_a_person(report):
    assert totals(report[0])["edge_cases_sent"] == (3, 3)
    edge = [x.customer_id for x in read_labels() if x.edge_case]
    assert all(not report[1][c]["settled"] for c in edge)


def test_the_engine_agrees_on_23_of_25_and_the_starters_rule_on_22(report):
    t = totals(report[0])
    assert t["risk_agrees"] == (23, 25)
    assert t["decision_agrees"] == (23, 25)
    assert t["starter_risk_agrees"] == (22, 25)
    assert t["starter_decision_agrees"] == (22, 25)


def test_the_two_that_disagree_are_the_labelled_low_edge_cases_the_engine_held_cautiously(report):
    off = [
        c
        for c, o in report[1].items()
        if o["risk_level"] != next(x.risk_level for x in read_labels() if x.customer_id == c)
    ]
    assert off == ["CUST-018", "CUST-021"]


def test_every_application_and_every_screening_is_accounted_for(report):
    t = totals(report[0])
    assert t["applications_accounted"] == (25, 25)
    assert t["screenings_accounted"] == (350, 350)
