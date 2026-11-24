"""Tests that the starter's Obligation and SectionSummary become cited facts and back unchanged."""

import json
import re

import pytest

from fsi_common.examples.data import COPIED_ATTRIBUTES, FACT_KINDS
from fsi_common.records import CheckResult, Extractor, Fact, Source
from sub_agent import Obligation, SectionSummary
from utils import PROJECT_ROOT
from utils.records import (
    COPIED_ATTRIBUTES as TOPIC_COPIED_ATTRIBUTES,
)
from utils.records import (
    DOCUMENT_FACT_KINDS,
    FACT_CONTEXT,
    SectionResult,
    StarterShapeError,
    fact_to_obligations,
    obligation_to_fact,
    records_to_section_summary,
    section_summary_to_records,
)

EXTRACTOR = Extractor(name="section-summariser", version="0.1.0")
PASSED = [CheckResult(check="quote-verbatim.v1", outcome="pass", detail="found in the paragraph")]


def _starter_examples() -> list[dict]:
    text = (PROJECT_ROOT / "sub_agent_instructions.md").read_text(encoding="utf-8")
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)```", text, flags=re.S)]


@pytest.fixture(scope="module")
def source():
    document = PROJECT_ROOT / "data" / "documents" / "PS26-4.md"
    from fsi_common.ids import digest_bytes

    return Source.build(
        key="PS26-4",
        title="Policy Statement PS26/4: Operational resilience and third-party technology risk",
        kind="document",
        digest=digest_bytes(document.read_bytes()),
        locator="03_document_summary_agent/data/documents/PS26-4.md",
        terms="Fictional sample data from the FSI hackathon starter",
    )


def _to_records(summary, source):
    return section_summary_to_records(
        summary,
        source=source,
        extractor=EXTRACTOR,
        model="claude-sonnet-5-5",
        prompt_version="1",
        checks_for=lambda obligation: PASSED,
    )


def test_the_instructions_hold_one_starter_example():
    assert len(_starter_examples()) == 1


@pytest.mark.parametrize("example", _starter_examples())
def test_every_starter_example_round_trips(example, source):
    summary = SectionSummary(**example)
    records = _to_records(summary, source)
    back = records_to_section_summary(records.result, records.facts)
    assert back == summary
    assert back.model_dump() == example


@pytest.mark.parametrize("example", _starter_examples())
def test_every_obligation_becomes_a_cited_fact(example, source):
    records = _to_records(SectionSummary(**example), source)
    for obligation, fact_id in zip(example["obligations"], records.result.fact_ids, strict=True):
        fact = records.facts[fact_id]
        assert fact.kind == "obligation"
        assert fact.subject.anchor == f"para:{obligation['paragraph']}"
        assert fact.quote == obligation["evidence"]
        assert fact.attributes == {
            "requirement": [obligation["requirement"]],
            "deadline": obligation["deadline"],
        }
        assert Fact.model_validate(fact.to_json(), context=FACT_CONTEXT) == fact


def test_a_null_deadline_and_a_repeated_obligation_round_trip(source):
    obligation = Obligation(
        requirement="Keep each self-assessment",
        paragraph="8.5",
        deadline=None,
        evidence="Firms must keep each self-assessment for at least 5 years",
    )
    summary = SectionSummary(
        number="8",
        title="Governance and accountability",
        summary="",
        obligations=[obligation, obligation],
    )
    records = _to_records(summary, source)
    assert len(records.facts) == 1
    assert len(records.result.fact_ids) == 2
    assert records_to_section_summary(records.result, records.facts) == summary


def test_a_section_with_no_obligations_round_trips(source):
    summary = SectionSummary(
        number="10", title="Next steps and contacts", summary="Webinars.", obligations=[]
    )
    records = _to_records(summary, source)
    assert records.facts == {}
    assert records_to_section_summary(records.result, records.facts) == summary


def test_the_same_obligation_gives_the_same_fact_id(source):
    example = SectionSummary(**_starter_examples()[0])
    assert _to_records(example, source).result == _to_records(example, source).result


def test_an_obligation_with_no_quote_fails_by_paragraph(source):
    obligation = Obligation(requirement="Notify", paragraph="7.1", deadline=None, evidence=" ")
    with pytest.raises(StarterShapeError, match="paragraph '7.1'"):
        obligation_to_fact(
            obligation,
            source=source,
            extractor=EXTRACTOR,
            model=None,
            prompt_version=None,
            checks=PASSED,
        )


def test_an_obligation_citing_two_paragraphs_fails_by_paragraph(source):
    obligation = Obligation(
        requirement="Notify", paragraph="7.1 and 7.2", deadline=None, evidence="Firms must"
    )
    with pytest.raises(StarterShapeError, match="paragraph '7.1 and 7.2'"):
        obligation_to_fact(
            obligation,
            source=source,
            extractor=EXTRACTOR,
            model=None,
            prompt_version=None,
            checks=PASSED,
        )


def test_an_obligation_with_no_checks_is_refused(source):
    obligation = Obligation(
        requirement="Notify", paragraph="7.1", deadline=None, evidence="Firms must"
    )
    with pytest.raises(StarterShapeError, match="paragraph '7.1'"):
        obligation_to_fact(
            obligation,
            source=source,
            extractor=EXTRACTOR,
            model=None,
            prompt_version=None,
            checks=[],
        )


def test_a_missing_fact_fails_and_names_the_section():
    result = SectionResult(
        number="7", title="Incident reporting", summary="s", fact_ids=["fact:0123456789abcdef"]
    )
    with pytest.raises(StarterShapeError, match="Section 7 lists facts that are not held"):
        records_to_section_summary(result, {})


def test_a_fact_of_another_kind_cannot_become_an_obligation(source):
    obligation = Obligation(
        requirement="Notify", paragraph="7.1", deadline=None, evidence="Firms must"
    )
    fact = obligation_to_fact(
        obligation,
        source=source,
        extractor=EXTRACTOR,
        model=None,
        prompt_version=None,
        checks=PASSED,
    )
    data = fact.to_json() | {"kind": "guidance"}
    other = Fact.build(
        context=FACT_CONTEXT, **{k: v for k, v in data.items() if k not in {"id", "schema"}}
    )
    with pytest.raises(StarterShapeError, match="is not an obligation"):
        fact_to_obligations(other)


def test_the_topic_declaration_is_the_one_the_shared_examples_use():
    assert DOCUMENT_FACT_KINDS == FACT_KINDS
    assert TOPIC_COPIED_ATTRIBUTES == COPIED_ATTRIBUTES == ("deadline",)


def _fact_of(source, **changes):
    fields = {
        "requirement": "Notify the regulator of a major incident",
        "paragraph": "7.1",
        "deadline": "within 4 hours of classifying an incident as a major incident",
        "evidence": "Firms must submit an initial notification to the FSOA within 4 hours",
    }
    return obligation_to_fact(
        Obligation(**(fields | changes)),
        source=source,
        extractor=EXTRACTOR,
        model="claude-sonnet-5-5",
        prompt_version="1",
        checks=PASSED,
    )


def test_a_rerun_that_rewords_the_requirement_gives_the_same_fact_id(source):
    first = _fact_of(source)
    rerun = _fact_of(source, requirement="Tell the FSOA within 4 hours of a major incident")
    assert rerun.id == first.id
    assert rerun.attributes["requirement"] != first.attributes["requirement"]


def _twins(*requirements):
    base = {
        "paragraph": "7.1",
        "deadline": "within 4 hours of classifying an incident as a major incident",
        "evidence": "Firms must submit an initial notification to the FSOA within 4 hours",
    }
    return [Obligation(requirement=r, **base) for r in requirements]


def _summary_of(*obligations):
    return SectionSummary(
        number="7", title="Incident reporting", summary="s", obligations=list(obligations)
    )


def test_a_fact_of_kind_obligation_always_holds_a_list_of_requirements(source):
    fact = _fact_of(source)
    assert fact.attributes["requirement"] == ["Notify the regulator of a major incident"]


def test_two_duties_with_one_quote_are_one_fact_holding_both_requirements_in_order(source):
    first, second = _twins("Notify the FSOA of a major incident", "Keep a log of each incident")
    summary = _summary_of(first, second)
    records = _to_records(summary, source)
    (fact_id,) = records.facts
    assert records.facts[fact_id].attributes["requirement"] == [
        "Notify the FSOA of a major incident",
        "Keep a log of each incident",
    ]
    assert records.result.fact_ids == [fact_id, fact_id]
    assert records_to_section_summary(records.result, records.facts) == summary


def test_the_order_returned_is_kept_across_other_obligations_and_repeats(source):
    a, b = _twins("First duty", "Second duty")
    other = Obligation(
        requirement="Intermediate report",
        paragraph="7.2",
        deadline=None,
        evidence="Firms must submit an intermediate report",
    )
    summary = _summary_of(a, other, b, a)
    records = _to_records(summary, source)
    assert len(records.facts) == 2
    assert len(records.result.fact_ids) == 4
    assert records_to_section_summary(records.result, records.facts) == summary


def test_the_requirements_of_a_shared_fact_do_not_change_its_id(source):
    (single,) = _to_records(_summary_of(*_twins("Notify")), source).facts
    (double,) = _to_records(_summary_of(*_twins("Notify", "Log")), source).facts
    assert single == double  # the ids; the requirements are not part of an id


def test_a_fact_whose_requirement_is_not_a_list_cannot_become_an_obligation(source):
    fact = _fact_of(source)
    data = fact.to_json() | {"attributes": {"requirement": "plain text", "deadline": None}}
    other = Fact.build(
        context=FACT_CONTEXT, **{k: v for k, v in data.items() if k not in {"id", "schema"}}
    )
    with pytest.raises(StarterShapeError, match="requirement"):
        fact_to_obligations(other)
    empty = data | {"attributes": {"requirement": [], "deadline": None}}
    other = Fact.build(
        context=FACT_CONTEXT, **{k: v for k, v in empty.items() if k not in {"id", "schema"}}
    )
    with pytest.raises(StarterShapeError, match="requirement"):
        fact_to_obligations(other)


def test_a_fact_listed_more_often_than_it_has_requirements_fails_and_names_it(source):
    records = _to_records(_summary_of(*_twins("Only one")), source)
    (fact_id,) = records.facts
    result = records.result.model_copy(update={"fact_ids": [fact_id, fact_id]})
    with pytest.raises(StarterShapeError, match=fact_id):
        records_to_section_summary(result, records.facts)


@pytest.mark.parametrize(
    "change",
    [
        {"evidence": "Firms must submit an initial notification to the FSOA"},
        {"deadline": "no later than 24 hours after the incident is first detected"},
        {"deadline": None},
        {"paragraph": "7.2"},
    ],
)
def test_a_changed_quote_deadline_or_paragraph_gives_another_fact(source, change):
    assert _fact_of(source, **change).id != _fact_of(source).id
