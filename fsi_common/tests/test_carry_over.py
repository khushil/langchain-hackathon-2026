"""Tests of whether a decision carries over to a rerun, asks again with the change, or none."""

import pytest
from pydantic import ValidationError

from fsi_common.examples.data import FACT_CONTEXT, build_examples
from fsi_common.records import CarryOver, Fact, carry_over, judged_differences


@pytest.fixture(scope="module")
def ex():
    return build_examples()


def _rerun(fact: Fact, change) -> Fact:
    data = {k: v for k, v in fact.to_json().items() if k not in {"id", "schema"}}
    change(data)
    return Fact.build(context=FACT_CONTEXT, **data)


def test_the_same_judged_content_carries_the_decision(ex):
    carried = carry_over(ex.accept_7_1, ex.fact_7_1)
    assert carried == CarryOver(outcome="carried", decision=ex.accept_7_1, differences=[])


def test_a_new_model_prompt_and_extractor_version_keep_the_decision_carried(ex):
    def new_versions(data):
        data["provenance"].update(model="another-model", prompt_version="7")
        data["provenance"]["extractor"]["version"] = "9.0.0"
        data["checks"][0]["detail"] = "compared after a change to the check's wording"

    rerun = _rerun(ex.fact_7_1, new_versions)
    assert rerun.id == ex.fact_7_1.id
    assert carry_over(ex.accept_7_1, rerun).outcome == "carried"
    assert carry_over(ex.accept_7_1, ex.fact_7_1_rerun).outcome == "carried"


def test_a_reworded_requirement_asks_again_and_names_it(ex):
    asked = carry_over(ex.accept_7_1, ex.fact_7_1_variant)
    assert asked.outcome == "ask_again"
    assert asked.decision == ex.accept_7_1
    assert asked.differences == ["attributes.requirement"]


def test_a_check_that_now_fails_asks_again_and_names_the_check(ex):
    def deadline_fails(data):
        data["checks"][1].update(outcome="fail", detail="not in paragraph 7.1")

    asked = carry_over(ex.accept_7_1, _rerun(ex.fact_7_1, deadline_fails))
    assert asked.outcome == "ask_again"
    assert asked.differences == ["checks.deadline-verbatim.v1"]


def test_a_fact_with_no_earlier_decision_is_asked_fresh(ex):
    assert carry_over(None, ex.fact_7_1) == CarryOver(
        outcome="fresh", decision=None, differences=[]
    )


def test_a_decision_on_another_id_is_no_decision_on_this_fact(ex):
    def new_quote(data):
        data["quote"] = "Firms must submit an initial notification to the FSOA"

    changed = _rerun(ex.fact_7_1, new_quote)
    assert changed.id != ex.fact_7_1.id
    assert carry_over(ex.accept_7_1, changed).outcome == "fresh"


def test_an_answered_question_carries_whatever_its_state(ex):
    answered = ex.question.model_validate(
        ex.question.to_json() | {"state": "answered", "decision_id": ex.answer.id}
    )
    assert carry_over(ex.answer, answered).outcome == "carried"


def test_differences_name_added_and_removed_fields():
    before = {"quote": "a", "attributes": {"deadline": "x"}}
    after = {"quote": "a", "attributes": {"deadline": "x", "actor": "firm"}, "kind": "k"}
    assert judged_differences(before, after) == ["attributes.actor", "kind"]
    assert judged_differences(before, before) == []


@pytest.mark.parametrize(
    ("outcome", "with_decision", "differences"),
    [
        ("fresh", True, []),
        ("carried", False, []),
        ("ask_again", True, []),
        ("carried", True, ["quote"]),
    ],
)
def test_a_carry_over_that_does_not_fit_its_outcome_is_refused(
    ex, outcome, with_decision, differences
):
    with pytest.raises(ValidationError, match="carry.outcome|asked"):
        CarryOver(
            outcome=outcome,
            decision=ex.accept_7_1 if with_decision else None,
            differences=differences,
        )
