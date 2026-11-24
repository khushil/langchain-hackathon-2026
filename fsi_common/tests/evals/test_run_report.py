"""Tests for the runner that applies evaluators and reports one line per measure."""

import pytest

from fsi_common.evals.measures import Measure
from fsi_common.evals.runner import run_evaluators


def found(example, output):
    return [Measure("found", output["hits"], example["total"], "things")]


def always_empty(example, output):
    return [Measure("empty", 0, 0, "nothing")]


def explodes(example, output):
    raise KeyError("missing field")


PAIRS = [({"key": "s1", "total": 4}, {"hits": 3}), ({"key": "s2", "total": 6}, {"hits": 6})]


def test_totals_add_the_examples_and_print_one_line_per_measure():
    report = run_evaluators(PAIRS, [found])
    assert report.ok
    assert report.exit_code == 0
    assert [m.line() for m in report.totals] == ["found: 9 of 10 things"]
    assert "found: 9 of 10 things (2 examples)" in report.render()
    assert "PASS" in report.render()


def test_per_example_lines_are_kept_when_asked_for():
    text = run_evaluators(PAIRS, [found]).render(per_example=True)
    assert "s1" in text and "found: 3 of 4 things" in text
    assert "s2" in text and "found: 6 of 6 things" in text


def test_a_required_measure_with_nothing_in_scope_fails_the_run():
    report = run_evaluators(PAIRS, [found, always_empty], required=["empty"])
    assert not report.ok
    assert report.exit_code == 1
    assert any("empty" in f and "none in scope" in f for f in report.failures)
    assert "FAIL" in report.render()


def test_a_measure_with_nothing_in_scope_is_only_reported_when_not_required():
    report = run_evaluators(PAIRS, [found, always_empty])
    assert report.ok
    assert "empty: none in scope (nothing)" in report.render()


def test_a_required_measure_that_no_evaluator_produced_fails_the_run():
    report = run_evaluators(PAIRS, [found], required=["invented"])
    assert not report.ok
    assert any("invented" in f and "no evaluator" in f for f in report.failures)


def test_an_evaluator_that_raises_fails_the_run_and_names_it_and_the_example():
    report = run_evaluators(PAIRS, [found, explodes])
    assert not report.ok
    failure = next(f for f in report.failures if "explodes" in f)
    assert "s1" in failure and "KeyError" in failure and "missing field" in failure
    assert [m.key for m in report.totals] == ["found"]


def test_a_run_over_no_pairs_scores_nothing_and_fails():
    report = run_evaluators([], [found])
    assert not report.ok
    assert any("no examples" in f for f in report.failures)
    assert report.totals == []
    assert "FAIL" in report.render()


def test_a_run_with_no_evaluators_fails():
    report = run_evaluators(PAIRS, [])
    assert not report.ok
    assert any("no evaluators" in f for f in report.failures)


def test_a_run_where_every_evaluator_raised_reports_fail_and_no_scores():
    report = run_evaluators(PAIRS, [explodes])
    assert report.totals == []
    assert report.exit_code == 1


def test_the_same_key_reported_with_two_populations_is_refused():
    def other(example, output):
        return [Measure("found", 1, 1, "something else")]

    report = run_evaluators(PAIRS, [found, other])
    assert not report.ok
    assert any("population" in f for f in report.failures)


def test_an_evaluator_returning_something_other_than_measures_fails_the_run():
    def wrong(example, output):
        return 0.5

    report = run_evaluators(PAIRS, [wrong])
    assert not report.ok
    assert any("wrong" in f for f in report.failures)


@pytest.mark.parametrize("count", [1, 3])
def test_the_example_count_is_stated(count):
    report = run_evaluators(PAIRS[:1] * count, [found])
    assert f"({count} example" in report.render()
