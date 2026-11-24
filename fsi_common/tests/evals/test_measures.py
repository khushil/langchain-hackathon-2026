"""Tests for the measure record that every evaluator reports."""

import pytest

from fsi_common.evals.measures import Measure, MeasureError, sum_measures


def test_a_measure_with_scope_scores_its_share_and_prints_its_counts():
    m = Measure("found", 37, 39, "labelled obligations")
    assert m.in_scope
    assert m.score == pytest.approx(37 / 39)
    assert m.line() == "found: 37 of 39 labelled obligations"


def test_a_measure_with_nothing_in_scope_has_no_score_and_says_so():
    m = Measure("found", 0, 0, "labelled obligations")
    assert not m.in_scope
    assert m.score is None
    assert m.line() == "found: none in scope (labelled obligations)"


def test_a_full_measure_is_full_and_a_lower_is_better_measure_is_full_at_zero():
    assert Measure("a", 3, 3, "x").is_full
    assert not Measure("a", 2, 3, "x").is_full
    assert Measure("b", 0, 5, "x", lower_is_better=True).is_full
    assert not Measure("b", 1, 5, "x", lower_is_better=True).is_full
    assert not Measure("c", 0, 0, "x").is_full


def test_a_numerator_above_its_denominator_is_refused():
    with pytest.raises(MeasureError, match="exceeds"):
        Measure("a", 4, 3, "x")


def test_a_negative_count_is_refused():
    with pytest.raises(MeasureError, match="negative"):
        Measure("a", -1, 3, "x")


def test_sum_measures_adds_counts_of_one_key():
    total = sum_measures(
        [Measure("a", 1, 2, "x"), Measure("a", 3, 4, "x"), Measure("a", 0, 0, "x")]
    )
    assert (total.key, total.numerator, total.denominator, total.population) == ("a", 4, 6, "x")


def test_sum_measures_refuses_two_populations_of_one_key():
    with pytest.raises(MeasureError, match="populations"):
        sum_measures([Measure("a", 1, 1, "x"), Measure("a", 1, 1, "y")])


def test_sum_measures_refuses_mixed_keys_and_empty_input():
    with pytest.raises(MeasureError, match="one key"):
        sum_measures([Measure("a", 1, 1, "x"), Measure("b", 1, 1, "x")])
    with pytest.raises(MeasureError, match="nothing to add"):
        sum_measures([])
