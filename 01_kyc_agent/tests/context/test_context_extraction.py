"""An application's reading becomes cited facts, each checked against its own words."""

import pytest
from kyc_fakes import reading_of

from context.errors import ApplicantReadError
from context.extraction import ApplicantRead, Detail, RelationRead, read_applicant
from context.reader import read_applications
from fsi_common.records import Fact
from utils.records import FACT_CONTEXT

MODEL, PROMPT = "claude-sonnet-5-5", "extract-test"
TEXT_015 = (
    "Applicant: Marta Harlan. Date of birth: 17 March 1971. Valdorian national. I'm a homemaker "
    "and my husband is a senior government official in Valdoria. Funds will come from my "
    "husband's salary and family savings, about $90,000."
)


def good_read() -> ApplicantRead:
    return ApplicantRead(
        full_name=Detail(value="Marta Harlan", quote="Marta Harlan"),
        date_of_birth=Detail(value="1971-03-17", quote="17 March 1971"),
        nationality=Detail(value="Valdorian", quote="Valdorian national"),
        occupation=Detail(value="homemaker", quote="homemaker"),
        source_of_funds=Detail(
            value="husband's salary and family savings",
            quote="my husband's salary and family savings",
        ),
        funds_amount=Detail(value="$90,000", quote="about $90,000"),
        relation=RelationRead(
            relation="husband",
            quote="my husband is a senior government official in Valdoria",
            related_name=None,
            related_office="senior government official in Valdoria",
        ),
    )


@pytest.fixture()
def application():
    read = read_applications(["CUST-015"])
    return read.source, read.units[0], read.unit_text[read.units[0].id]


def read(application, summary):
    source, unit, text = application
    return read_applicant(
        summary, source=source, unit=unit, text=text, model=MODEL, prompt_version=PROMPT
    )


def by_kind(result):
    return {f.kind: f for f in result.facts}


def test_the_application_in_the_data_is_the_one_the_tests_read(application):
    assert application[2] == TEXT_015


def test_each_detail_is_a_fact_that_quotes_the_application_and_passes(application):
    result = read(application, good_read())
    facts = by_kind(result)
    assert set(facts) == {
        "applicant_name",
        "birth_date",
        "nationality",
        "occupation",
        "source_of_funds",
        "funds_amount",
        "relation",
    }
    assert all(f.passed_checks for f in result.facts)
    assert all(f.status.status == "documented" for f in result.facts)
    assert facts["birth_date"].attributes == {"value": "1971-03-17"}
    assert facts["funds_amount"].attributes == {"amount": "$90,000"}
    assert facts["relation"].attributes == {
        "relation": "husband",
        "related_name": None,
        "related_office": "senior government official in Valdoria",
    }
    assert result.questions == []
    for fact in result.facts:
        assert fact.provenance.model == MODEL
        assert fact.provenance.prompt_version == PROMPT
        assert fact.subject.anchor == "row:CUST-015"
        Fact.model_validate(fact.to_json(), context=FACT_CONTEXT)


def test_a_reading_without_a_relation_gives_no_relation_fact(application):
    summary = good_read().model_copy(update={"relation": None})
    assert "relation" not in by_kind(read(application, summary))


def test_a_name_the_application_does_not_write_fails_and_asks_what_the_name_is(application):
    summary = good_read().model_copy(
        update={"full_name": Detail(value="Marta Harlan-Smith", quote="Marta Harlan")}
    )
    result = read(application, summary)
    name = by_kind(result)["applicant_name"]
    assert not name.passed_checks
    assert [c.check for c in name.checks if c.outcome == "fail"] == ["name-verbatim.v1"]
    assert result.applicant.name is None
    [question] = result.questions
    assert question.reason == "missing_data"
    assert question.about.anchor == "row:CUST-015"
    assert name.id in question.cites


def test_a_quote_that_is_not_in_the_application_fails_its_check_and_stays_a_fact(application):
    summary = good_read().model_copy(
        update={"nationality": Detail(value="Valdorian", quote="a Valdorian passport holder")}
    )
    result = read(application, summary)
    nationality = by_kind(result)["nationality"]
    assert [c.outcome for c in nationality.checks] == ["fail"]
    assert result.questions == []


def test_a_date_that_does_not_read_as_its_quote_fails_and_leaves_no_date_of_birth(application):
    summary = good_read().model_copy(
        update={"date_of_birth": Detail(value="1971-17-03", quote="17 March 1971")}
    )
    result = read(application, summary)
    assert not by_kind(result)["birth_date"].passed_checks
    assert result.applicant.date_of_birth is None
    assert result.applicant.name == "Marta Harlan"


def test_what_a_passing_reading_gives_the_screening(application):
    result = read(application, good_read())
    applicant = result.applicant
    assert applicant.customer_id == "CUST-015"
    assert (applicant.name, applicant.date_of_birth) == ("Marta Harlan", "1971-03-17")
    assert applicant.relation.related_office == "senior government official in Valdoria"
    assert applicant.relation.related_name is None


def test_a_blank_quote_is_no_fact_and_is_asked_about_never_dropped(application):
    summary = good_read().model_copy(update={"occupation": Detail(value="homemaker", quote=" ")})
    result = read(application, summary)
    assert "occupation" not in by_kind(result)
    [question] = result.questions
    assert "occupation" in question.question
    assert question.reason == "missing_data"


def test_a_blank_name_is_refused_by_name(application):
    summary = good_read().model_copy(update={"full_name": Detail(value="", quote="")})
    result = read(application, summary)
    assert result.applicant.name is None
    assert any("name" in q.question for q in result.questions)


def test_the_same_reading_twice_gives_the_same_facts_and_ids(application):
    first = read(application, good_read())
    second = read(application, good_read())
    assert [f.id for f in first.facts] == [f.id for f in second.facts]


def test_a_model_wording_a_detail_differently_keeps_the_fact_id(application):
    other = good_read().model_copy(
        update={"nationality": Detail(value="Valdoria", quote="Valdorian national")}
    )
    first = by_kind(read(application, good_read()))["nationality"]
    second = by_kind(read(application, other))["nationality"]
    assert first.id == second.id
    assert first.judged_basis() != second.judged_basis()


def test_an_application_with_no_text_is_refused(application):
    source, unit, _ = application
    with pytest.raises(ApplicantReadError, match="CUST-015"):
        read_applicant(
            good_read(), source=source, unit=unit, text="", model=MODEL, prompt_version=PROMPT
        )


def test_a_relation_that_fails_a_check_is_asked_about_as_a_failed_name_is(application):
    relation = good_read().relation.model_copy(update={"related_office": "a senior official"})
    result = read(application, good_read().model_copy(update={"relation": relation}))
    assert not by_kind(result)["relation"].passed_checks
    assert result.applicant.relation is None
    [question] = result.questions
    assert question.reason == "missing_data"
    assert "husband" in question.question
    assert by_kind(result)["relation"].id in question.cites


def test_a_relation_given_with_no_quote_is_asked_about_and_never_dropped(application):
    relation = good_read().relation.model_copy(update={"quote": " "})
    result = read(application, good_read().model_copy(update={"relation": relation}))
    assert "relation" not in by_kind(result)
    assert result.applicant.relation is None
    [question] = result.questions
    assert question.reason == "missing_data"
    assert "husband" in question.question and "relation" in question.question


def test_a_relation_with_nothing_in_it_is_no_relation_and_asks_nothing(application):
    empty = RelationRead(relation="", quote="", related_name=None, related_office=None)
    result = read(application, good_read().model_copy(update={"relation": empty}))
    assert "relation" not in by_kind(result) and result.questions == []


def test_the_markers_of_what_is_unsettled_carry_one_prefix_only():
    from outcomes import outcome_of

    detail = reading_of("CUST-001").occupation.model_copy(update={"quote": "", "value": ""})
    result = outcome_of(
        "CUST-001", reading_of("CUST-001").model_copy(update={"occupation": detail})
    )
    [marker] = [m for m in result.proposal.attributes["unsettled"] if m.startswith("question:")]
    assert marker.count("question:") == 1
