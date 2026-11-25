"""One application against one list entry: a fact when the names are alike, a score when not."""

import pytest
from kyc_fakes import reading_of

from context.checks import DOB_CHECK, QUOTE_CHECK, SCORE_CHECK
from context.extraction import read_applicant
from context.reader import entries_of, read_applications, read_screenings, screening_anchor
from context.screening import MATCH_THRESHOLD, NEAR_FLOOR, screen_pair
from tools.screening import MATCH_THRESHOLD as STARTER_THRESHOLD

ENTRIES = {e.anchor_part: e for e in entries_of()}


def applicant(customer_id, **kwargs):
    apps = read_applications([customer_id])
    unit = apps.units[0]
    return read_applicant(
        reading_of(customer_id, **kwargs),
        source=apps.source,
        unit=unit,
        text=apps.unit_text[unit.id],
        model="m",
        prompt_version="p",
    ).applicant


def pair(customer_id, part, **kwargs):
    screenings = read_screenings([customer_id])
    unit = next(u for u in screenings.units if u.anchor == screening_anchor(customer_id, part))
    return screen_pair(
        applicant(customer_id, **kwargs),
        ENTRIES[part],
        source=screenings.source,
        unit=unit,
        unit_text=screenings.unit_text[unit.id],
    )


def test_the_threshold_is_the_starters_and_the_floor_is_ours():
    assert MATCH_THRESHOLD == STARTER_THRESHOLD == 0.85
    assert NEAR_FLOOR == 0.60


def test_an_exact_name_and_date_of_birth_on_the_sanctions_list_settles_by_the_checks():
    result = pair("CUST-016", "sanctions-4")
    fact = result.fact
    assert fact.kind == "screening"
    assert fact.quote == "Rurik Zelenko"
    assert fact.attributes["name_score"] == "1.00"
    assert fact.attributes["dob_agrees"] is True
    assert fact.attributes["outcome"] == "settled"
    assert result.settles is True
    assert result.question is None
    assert {c.check for c in fact.checks} == {QUOTE_CHECK, SCORE_CHECK, DOB_CHECK}
    assert fact.passed_checks


def test_the_same_name_with_another_date_of_birth_is_kept_and_asked_with_both_readings():
    result = pair("CUST-018", "sanctions-5")
    fact = result.fact
    assert fact.attributes["name_score"] == "1.00"
    assert fact.attributes["dob_agrees"] is False
    assert fact.attributes["outcome"] == "unsettled"
    assert result.settles is False
    assert "dates of birth differ" in fact.attributes["why_unsettled"]
    assert any("dates of birth differ" in line for line in fact.attributes["reading_different"])
    assert any("identical" in line for line in fact.attributes["reading_same"])
    question = result.question
    assert question.reason == "ambiguous_meaning"
    assert question.priority == "high"
    assert fact.id in question.cites
    assert "Ivana Strahov" in question.question and "sanctions" in question.question
    readings = result.readings
    assert readings.same == fact.attributes["reading_same"]
    assert readings.different == fact.attributes["reading_different"]


def test_a_near_name_over_the_threshold_with_the_same_date_of_birth_is_still_asked():
    result = pair("CUST-003", "sanctions-1")
    assert result.fact.attributes["name_score"] == "0.91"
    assert result.fact.attributes["dob_agrees"] is True
    assert result.settles is False
    assert result.question is not None
    assert any("agree" in line for line in result.readings.same)
    assert any("not identical" in line or "spelled" in line for line in result.readings.different)


def test_a_pep_name_match_cannot_be_settled_because_the_list_has_no_date_of_birth():
    result = pair("CUST-021", "pep-1")
    fact = result.fact
    assert fact.attributes["name_score"] == "0.92"
    assert fact.attributes["dob_agrees"] is None
    assert fact.attributes["entry_dob"] is None
    assert "no date of birth" in fact.attributes["why_unsettled"]
    assert result.question.priority == "medium"
    assert any("Deputy Minister of Finance" in line for line in result.readings.different)


def test_a_pep_exact_match_that_states_the_office_has_that_on_the_side_of_the_same_person():
    result = pair("CUST-002", "pep-1")
    assert result.settles is False
    assert any("Deputy Minister of Finance" in line for line in result.readings.same)


def test_a_name_below_the_floor_has_no_fact_and_its_score_is_the_reason():
    result = pair("CUST-001", "sanctions-1")
    assert result.fact is None and result.question is None
    assert result.reason.startswith("No likeness")
    assert "0.2" in result.reason or "0.3" in result.reason or "0.4" in result.reason
    assert "Dmitry Volkonskiy" in result.reason


def test_a_weak_likeness_between_the_floor_and_the_threshold_is_a_near_fact_with_a_low_question():
    result = pair("CUST-015", "pep-1")
    assert result.fact.attributes["strength"] == "near"
    assert float(result.fact.attributes["name_score"]) < MATCH_THRESHOLD
    assert result.question.priority == "low"


def test_the_screening_of_a_name_that_did_not_pass_its_check_is_not_run_and_says_so():
    result = pair("CUST-001", "sanctions-1", name="Sarah Mitchell-Jones")
    assert result.fact is None and result.question is None
    assert result.reason.startswith("Not screened")
    assert result.not_run is True


def test_no_name_is_special_cased():
    import inspect

    import context.screening as module

    source = inspect.getsource(module)
    assert "CUST-" not in source


@pytest.mark.parametrize("planted", ["0.95", "1.00"])
def test_a_screening_whose_score_is_changed_fails_the_score_check(planted):
    from context.checks import check_score

    fact = pair("CUST-003", "sanctions-1").fact
    assert (
        check_score(
            fact.attributes["applicant_name"], fact.attributes["entry_name"], planted
        ).outcome
        == "fail"
    )


def test_the_floor_sits_in_the_gap_the_starters_names_leave():
    from kyc_fakes import NAMES

    from tools.screening import name_similarity

    scores = sorted(
        name_similarity(name, entry.name) for name in NAMES.values() for entry in entries_of()
    )
    below = [s for s in scores if s < NEAR_FLOOR]
    over = [s for s in scores if NEAR_FLOOR <= s < MATCH_THRESHOLD]
    assert len(scores) == 350
    assert round(max(below), 3) == 0.593
    assert [round(s, 3) for s in over] == [0.615, 0.615, 0.640]
    assert not [s for s in scores if MATCH_THRESHOLD <= s < 0.9]
