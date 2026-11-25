"""The seven measures: each a count over a stated population, none calling a model."""

import pytest

from evals import evaluators as ev
from evals.build_dataset import read_examples
from evals.reference_assessments import reference_assessments

EXAMPLES = read_examples()
FIRST = EXAMPLES[0]


def assessment(tx, score, decision=None, confidence=0.9):
    return {
        "transaction_id": tx,
        "risk_score": score,
        "decision": decision or ("block" if score >= 70 else "approve"),
        "confidence": confidence,
    }


def scored(example, output):
    return {m.key: m for m in ev.evaluate_pair(example, output)}


def test_the_reference_assessments_score_in_full_on_every_measure_of_every_example():
    for example in EXAMPLES:
        for measure in ev.evaluate_pair(example, reference_assessments(example)):
            assert measure.is_full or not measure.in_scope, (example["key"], measure.line())


def test_the_measures_are_these_seven_in_this_order():
    assert ev.MEASURE_KEYS == (
        "assessed",
        "decisions_agree",
        "blocks_found",
        "false_blocks",
        "scores_in_band",
        "ambiguous_flagged",
        "clear_not_flagged",
    )
    assert [m.key for m in ev.evaluate_pair(FIRST, [])] == list(ev.MEASURE_KEYS)


def test_each_measure_states_its_population_over_the_first_example():
    populations = {m.key: (m.denominator, m.population) for m in ev.evaluate_pair(FIRST, [])}
    assert populations == {
        "assessed": (6, "labelled transactions"),
        "decisions_agree": (6, "labelled transactions"),
        "blocks_found": (2, "labelled blocks"),
        "false_blocks": (4, "labelled approvals"),
        "scores_in_band": (6, "labelled transactions"),
        "ambiguous_flagged": (1, "labelled ambiguous transactions"),
        "clear_not_flagged": (5, "labelled clear transactions"),
    }


def test_the_whole_data_has_eleven_labelled_transactions_with_three_blocks_and_two_ambiguous():
    first, second, _ = EXAMPLES
    totals = {}
    for example in (first, second):
        for m in ev.evaluate_pair(example, []):
            totals[m.key] = totals.get(m.key, 0) + m.denominator
    assert totals["assessed"] == 11
    assert (totals["blocks_found"], totals["false_blocks"]) == (3, 8)
    assert (totals["ambiguous_flagged"], totals["clear_not_flagged"]) == (2, 9)


def test_a_transaction_the_assessor_never_assessed_misses_every_measure_but_false_blocks():
    result = scored(FIRST, [])
    assert [(k, m.numerator) for k, m in result.items()] == [
        ("assessed", 0),
        ("decisions_agree", 0),
        ("blocks_found", 0),
        ("false_blocks", 0),
        ("scores_in_band", 0),
        ("ambiguous_flagged", 0),
        ("clear_not_flagged", 0),
    ]
    assert result["false_blocks"].is_full and not result["assessed"].is_full


def test_a_score_counts_as_in_band_up_to_twenty_points_from_the_analysts_and_no_further():
    base = reference_assessments(FIRST)
    for gap, expected in ((20, 6), (21, 5)):
        moved = [dict(a) for a in base]
        target = next(a for a in moved if a["transaction_id"] == "TX-1001")
        target["risk_score"] = 5 + gap
        assert scored(FIRST, moved)["scores_in_band"].numerator == expected


@pytest.mark.parametrize("bad", ["45", None, 45.5, True, float("nan")])
def test_a_score_that_is_not_a_whole_number_is_outside_the_band(bad):
    moved = [dict(a) for a in reference_assessments(FIRST)]
    next(a for a in moved if a["transaction_id"] == "TX-1003")["risk_score"] = bad
    assert scored(FIRST, moved)["scores_in_band"].numerator == 5


def test_a_transaction_is_flagged_when_its_confidence_is_below_the_starters_threshold():
    base = reference_assessments(FIRST)
    flagged = {a["transaction_id"] for a in base if a["confidence"] < 0.7}
    assert flagged == {"TX-1003"}
    for confidence, count in ((0.69, 1), (0.7, 0)):
        moved = [dict(a) for a in base]
        next(a for a in moved if a["transaction_id"] == "TX-1003")["confidence"] = 0.9
        next(a for a in moved if a["transaction_id"] == "TX-1001")["confidence"] = confidence
        assert scored(FIRST, moved)["clear_not_flagged"].numerator == 5 - count


def test_an_assessment_for_a_transaction_nobody_labelled_is_not_counted():
    moved = [*reference_assessments(FIRST), assessment("TX-9999", 5)]
    assert all(m.is_full for m in ev.evaluate_pair(FIRST, moved))


def test_the_later_weeks_four_reviews_are_scored_by_the_same_measures():
    later = EXAMPLES[2]
    result = scored(later, reference_assessments(later))
    assert result["blocks_found"].denominator == 1 and result["assessed"].denominator == 4


def test_the_starters_decision_log_reads_as_assessments_in_the_same_shape():
    log = [
        {
            "transaction_id": "TX-1001",
            "risk_score": 5,
            "confidence": 0.9,
            "agent_decision": "approve",
            "final_decision": "approve",
            "decided_by": "agent",
            "reason": "x",
        },
    ]
    assert ev.assessments_from_log(log) == [assessment("TX-1001", 5)]


def test_the_runs_raw_records_read_as_assessments_and_a_transaction_with_none_is_left_out():
    raw = {
        "TX-1001": {
            "audit": {
                "transaction_id": "TX-1001",
                "risk_score": 5,
                "model_confidence": 0.9,
                "confidence": 0.9,
                "agent_decision": "approve",
                "reason": "x",
            },
            "reply": "ok",
        },
        "TX-1002": {"audit": None, "reply": "nothing"},
    }
    assert ev.assessments_from_raw(raw) == [assessment("TX-1001", 5)]


def test_the_langsmith_evaluators_return_a_key_a_score_and_a_comment_with_the_counts():
    outputs = {"assessments": reference_assessments(FIRST)}
    functions = ev.langsmith_evaluators()
    assert [f.__name__ for f in functions] == list(ev.MEASURE_KEYS)
    result = functions[0](outputs, FIRST["reference_outputs"])
    assert result == {"key": "assessed", "score": 1.0, "comment": "6 of 6 labelled transactions"}
    none = functions[5]({"assessments": []}, {"labels": {}})
    assert none["score"] is None and "none in scope" in none["comment"]


def test_a_malformed_output_or_reference_is_refused_by_name():
    with pytest.raises(ev.MalformedAssessmentError, match="assessment"):
        ev.evaluate_pair(FIRST, [{"transaction_id": "TX-1001"}])
    with pytest.raises(ev.MalformedAssessmentError, match="labels"):
        ev.evaluate_pair({"reference_outputs": {}}, [])


@pytest.mark.parametrize("bad", ["0.5", None, float("nan"), True])
def test_a_confidence_that_is_not_a_number_is_never_a_flag(bad):
    moved = [dict(a) for a in reference_assessments(FIRST)]
    next(a for a in moved if a["transaction_id"] == "TX-1003")["confidence"] = bad
    result = scored(FIRST, moved)
    assert result["ambiguous_flagged"].numerator == 0


def test_the_log_is_read_for_what_the_agent_proposed_not_for_what_a_person_decided_after():
    log = [
        {
            "transaction_id": "TX-1003",
            "risk_score": 45,
            "confidence": 0.5,
            "agent_decision": "approve",
            "final_decision": "block",
            "decided_by": "human",
            "reason": "x",
        }
    ]
    assert ev.assessments_from_log(log)[0]["decision"] == "approve"
