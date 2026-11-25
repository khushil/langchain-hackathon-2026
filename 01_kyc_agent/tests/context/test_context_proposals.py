"""The proposal for each application: settled by the checks, or cautious and put to a person."""

import inspect

import pytest
from kyc_fakes import NAMES, reading_of
from outcomes import outcome_of

import context.proposals as module
from context.checks import PROPOSAL_CHECK, check_proposal
from context.extraction import RelationRead
from context.proposals import decide

SETTLED_HIGH = ["CUST-016", "CUST-020", "CUST-025"]
SETTLED_LOW = [
    "CUST-001",
    "CUST-004",
    "CUST-005",
    "CUST-006",
    "CUST-007",
    "CUST-008",
    "CUST-009",
    "CUST-010",
    "CUST-022",
    "CUST-024",
]


def proposal(customer_id, **kwargs):
    return outcome_of(customer_id, **kwargs).proposal


@pytest.mark.parametrize("customer_id", SETTLED_HIGH)
def test_an_exact_name_and_date_of_birth_on_the_sanctions_list_is_settled_high(customer_id):
    result = outcome_of(customer_id)
    attributes = result.proposal.attributes
    assert (attributes["risk_level"], attributes["decision"]) == ("high", "reject")
    assert attributes["settled"] is True
    assert "Exact name and date of birth match" in attributes["basis"]
    assert result.proposal.status.status == "inferred"
    assert result.questions == []
    assert result.proposal.passed_checks


@pytest.mark.parametrize("customer_id", SETTLED_LOW)
def test_no_likeness_to_any_entry_is_settled_low_with_every_score_on_the_list(customer_id):
    result = outcome_of(customer_id)
    attributes = result.proposal.attributes
    assert (attributes["risk_level"], attributes["decision"]) == ("low", "approve")
    assert attributes["settled"] is True
    assert "No likeness to any of the 14 list entries" in attributes["basis"]
    assert result.questions == []
    assert len(result.reasons) == 14
    assert all(r.startswith("No likeness") for r in result.reasons.values())
    assert [f.kind for f in result.facts] == ["proposal"]


UNSETTLED = [f"CUST-{n:03d}" for n in (2, 3, 11, 12, 13, 14, 15, 17, 18, 19, 21, 23)]


@pytest.mark.parametrize("customer_id", UNSETTLED)
def test_everything_else_is_the_cautious_reading_with_a_question_for_a_person(customer_id):
    result = outcome_of(customer_id)
    attributes = result.proposal.attributes
    assert (attributes["risk_level"], attributes["decision"]) == ("high", "reject")
    assert attributes["settled"] is False
    assert result.proposal.status.status == "unknown"
    assert result.questions
    assert set(result.readings) == {q.id for q in result.questions}
    assert "until a person answers" in attributes["basis"]


def test_the_three_edge_cases_are_sent_to_a_person_with_both_readings():
    for customer_id in ("CUST-015", "CUST-018", "CUST-021"):
        result = outcome_of(customer_id)
        assert result.proposal.attributes["settled"] is False
        for readings in result.readings.values():
            assert readings.same and readings.different


def test_a_relation_with_an_office_and_no_name_is_a_question_the_lists_cannot_answer():
    result = outcome_of("CUST-015")
    [question] = [q for q in result.questions if q.reason == "missing_data"]
    assert "husband" in question.question
    readings = result.readings[question.id]
    assert any("Valdoria" in line for line in readings.same)
    assert any("no name" in line for line in readings.different)
    assert "relation" in result.proposal.attributes["unsettled"]


def test_the_same_relation_with_no_office_is_context_and_asks_nothing():
    reading = reading_of("CUST-001").model_copy(
        update={
            "relation": RelationRead(
                relation="employer",
                quote="a logistics company",
                related_name=None,
                related_office=None,
            )
        }
    )
    result = outcome_of("CUST-001", reading)
    assert result.proposal.attributes["settled"] is True
    assert result.questions == []


def test_a_name_that_did_not_pass_is_asked_and_never_settled_low():
    reading = reading_of("CUST-001", name="Sarah Mitchell-Jones")
    result = outcome_of("CUST-001", reading)
    attributes = result.proposal.attributes
    assert attributes["settled"] is False
    assert attributes["name_checked"] is False
    assert (attributes["risk_level"], attributes["decision"]) == ("high", "reject")
    assert [q.reason for q in result.questions] == ["missing_data"]
    assert len(result.reasons) == 14
    assert all(r.startswith("Not screened") for r in result.reasons.values())


def test_every_screening_ends_as_a_fact_or_a_reason_and_none_both():
    result = outcome_of("CUST-020")
    anchors = {f.subject.anchor for f in result.facts if f.kind == "screening"}
    assert len(anchors) + len(result.reasons) == 14
    assert not anchors & set(result.reasons)


def test_a_settled_sanctions_match_beats_the_other_lists_questions():
    result = outcome_of("CUST-020")
    assert result.proposal.attributes["settled"] is True
    assert result.questions == []
    assert any(f.attributes.get("list") == "pep" for f in result.facts if f.kind == "screening")


def test_a_changed_reading_gives_the_same_proposal_id_and_another_judged_basis():
    base = proposal("CUST-016")
    moved = reading_of("CUST-016")
    wrong = moved.date_of_birth.model_copy(update={"value": "1971-04-18"})
    changed = proposal("CUST-016", reading=moved.model_copy(update={"date_of_birth": wrong}))
    assert base.attributes["settled"] is True
    assert changed.attributes["settled"] is False  # the date no longer reads as its words
    assert base.id == changed.id
    assert base.judged_basis() != changed.judged_basis()


@pytest.mark.parametrize(
    ("name_checked", "match", "unsettled", "expected"),
    [
        (True, "X", [], (True, "high", "reject")),
        (True, None, [], (True, "low", "approve")),
        (True, None, ["a"], (False, "high", "reject")),
        (False, None, [], (False, "high", "reject")),
        (False, "X", ["a"], (True, "high", "reject")),
    ],
)
def test_decide_is_the_one_rule(name_checked, match, unsettled, expected):
    result = decide(name_checked=name_checked, sanctions_match=match, unsettled=unsettled)
    assert tuple(result) == expected


@pytest.mark.parametrize(
    "change",
    [
        {"risk_level": "low"},
        {"decision": "approve"},
        {"settled": True},
        {"unsettled": []},
        {"sanctions_match": "Somebody"},
    ],
)
def test_a_proposal_changed_after_it_was_made_fails_its_check(change):
    attributes = dict(proposal("CUST-003").attributes)
    assert check_proposal(attributes).outcome == "pass"
    failed = check_proposal({**attributes, **change})
    assert (failed.check, failed.outcome) == (PROPOSAL_CHECK, "fail")


def test_no_customer_is_named_in_any_rule():
    source = inspect.getsource(module)
    assert "CUST-" not in source
    assert not any(name.split()[-1] in source for name in NAMES.values())


def moved(customer_id, **changes):
    return reading_of(customer_id).model_copy(update=changes)


def test_a_detail_that_failed_its_check_leaves_the_application_unsettled():
    detail = reading_of("CUST-001").source_of_funds.model_copy(
        update={"quote": "wages from a bakery"}
    )
    result = outcome_of("CUST-001", moved("CUST-001", source_of_funds=detail))
    attributes = result.proposal.attributes
    assert attributes["settled"] is False
    assert "detail:source_of_funds" in attributes["unsettled"]
    assert "source of funds" in attributes["basis"]
    assert (attributes["risk_level"], attributes["decision"]) == ("high", "reject")


def test_a_detail_the_reading_gave_no_quote_for_leaves_the_application_unsettled_and_asked():
    blank = reading_of("CUST-001").occupation.model_copy(update={"quote": "", "value": ""})
    result = outcome_of("CUST-001", moved("CUST-001", occupation=blank))
    attributes = result.proposal.attributes
    assert attributes["settled"] is False
    assert [q.reason for q in result.questions] == ["missing_data"]
    assert "occupation" in result.questions[0].question
    assert result.questions[0].id in attributes["unsettled"]


def test_a_relation_whose_words_are_not_in_the_application_is_asked_and_unsettled():
    relation = reading_of("CUST-015").relation.model_copy(
        update={"related_office": "senior official in the Valdorian government"}
    )
    result = outcome_of("CUST-015", moved("CUST-015", relation=relation))
    asked = [q for q in result.questions if "relation" in q.question and "husband" in q.question]
    assert asked and all(q.reason == "missing_data" for q in asked)
    assert result.proposal.attributes["settled"] is False
    assert any(m.startswith("detail:relation") for m in result.proposal.attributes["unsettled"])


def test_a_settled_sanctions_match_stays_settled_when_another_detail_failed():
    detail = reading_of("CUST-016").occupation.model_copy(update={"quote": "a made up quote"})
    result = outcome_of("CUST-016", moved("CUST-016", occupation=detail))
    assert result.proposal.attributes["settled"] is True
    assert result.proposal.attributes["risk_level"] == "high"
