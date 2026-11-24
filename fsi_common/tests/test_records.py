"""Tests of the record types: ids from content, deterministic output, and each refusal."""

import pytest
from pydantic import ValidationError

from fsi_common.examples.data import (
    FACT_CONTEXT,
    FACT_KINDS,
    REVIEWER,
    build_examples,
    paragraph_anchors,
)
from fsi_common.records import (
    Brief,
    Decision,
    Fact,
    OpenQuestion,
    Person,
    SignOff,
    Statement,
    UnitAccounting,
    fact_topic_context,
    judged_digest,
    record_digest,
)


@pytest.fixture(scope="module")
def ex():
    return build_examples()


def _error_types(exc_info) -> set[str]:
    return {error["type"] for error in exc_info.value.errors()}


def test_two_builds_give_identical_records(ex):
    again = build_examples()
    assert [r.to_json() for r in vars(ex).values()] == [r.to_json() for r in vars(again).values()]


def test_every_record_reads_back_unchanged(ex):
    for record in vars(ex).values():
        context = FACT_CONTEXT if isinstance(record, Fact) else None
        assert type(record).model_validate(record.to_json(), context=context) == record


def test_source_id_comes_from_kind_key_and_digest(ex):
    renamed = ex.document.to_json() | {"title": "Another title", "locator": "elsewhere.md"}
    assert type(ex.document).build(
        **{k: v for k, v in renamed.items() if k not in {"id", "schema"}}
    ).id == (ex.document.id)


def test_fact_id_ignores_provenance_status_and_checks(ex):
    data = ex.fact_7_1.to_json()
    data["provenance"]["model"] = "another-model"
    data["checks"] = [{"check": "quote-verbatim.v2", "outcome": "pass", "detail": "found"}]
    assert Fact.model_validate(data, context=FACT_CONTEXT).id == ex.fact_7_1.id


def _rebuilt(fact: Fact, **changes) -> Fact:
    fields = {k: v for k, v in fact.to_json().items() if k not in {"id", "schema"}}
    return Fact.build(context=FACT_CONTEXT, **(fields | changes))


def test_a_rerun_with_a_paraphrased_requirement_keeps_the_fact_id(ex):
    attributes = ex.fact_7_1.attributes | {"requirement": "Tell the FSOA about a major incident"}
    rerun = _rebuilt(ex.fact_7_1, attributes=attributes)
    assert rerun.id == ex.fact_7_1.id
    assert rerun.attributes["requirement"] != ex.fact_7_1.attributes["requirement"]


def test_fact_id_changes_with_the_quote(ex):
    data = ex.fact_7_1.to_json()
    data["quote"] = "Firms must submit an initial notification"
    with pytest.raises(ValidationError) as exc_info:
        Fact.model_validate(data, context=FACT_CONTEXT)
    assert _error_types(exc_info) == {"id.recompute"}
    assert _rebuilt(ex.fact_7_1, quote=data["quote"]).id != ex.fact_7_1.id


def test_fact_id_changes_with_the_deadline_as_written(ex):
    attributes = ex.fact_7_1.attributes | {"deadline": "within 24 hours"}
    assert _rebuilt(ex.fact_7_1, attributes=attributes).id != ex.fact_7_1.id


def test_fact_id_follows_the_topic_declaration(ex):
    nothing_copied = fact_topic_context(kinds=FACT_KINDS, copied_attributes=())
    with pytest.raises(ValidationError) as exc_info:
        Fact.model_validate(ex.fact_7_1.to_json(), context=nothing_copied)
    assert _error_types(exc_info) == {"id.recompute"}


def test_fact_refuses_a_kind_outside_the_topic_list(ex):
    data = ex.fact_7_1.to_json() | {"kind": "advice"}
    data = {k: v for k, v in data.items() if k not in {"id", "schema"}}
    with pytest.raises(ValidationError, match="kind 'advice' is not in the topic's list"):
        Fact.build(context=FACT_CONTEXT, **data)


def test_a_fact_without_the_topic_declaration_is_refused(ex):
    with pytest.raises(ValidationError, match="no topic declaration") as exc_info:
        Fact.model_validate(ex.fact_7_1.to_json())
    assert _error_types(exc_info) == {"fact.kind"}


def test_the_judged_basis_leaves_out_provenance_and_check_details(ex):
    judged = ex.fact_7_1.judged_basis()
    assert set(judged) == {"kind", "subject", "quote", "attributes", "checks"}
    assert judged["checks"] == [
        {"check": "deadline-verbatim.v1", "outcome": "pass"},
        {"check": "quote-verbatim.v1", "outcome": "pass"},
    ]
    assert judged_digest(ex.fact_7_1_rerun) == judged_digest(ex.fact_7_1)
    assert record_digest(ex.fact_7_1_rerun) != record_digest(ex.fact_7_1)


@pytest.mark.parametrize("quote", [None, "", "   "])
def test_fact_refuses_a_missing_or_blank_quote(ex, quote):
    data = ex.fact_7_1.to_json() | {"quote": quote}
    with pytest.raises(ValidationError) as exc_info:
        Fact.model_validate(data, context=FACT_CONTEXT)
    assert _error_types(exc_info) == {"fact.quote"}


def test_fact_passed_checks_is_false_when_one_check_failed(ex):
    data = ex.fact_7_1.to_json()
    data["checks"][1]["outcome"] = "fail"
    assert Fact.model_validate(data, context=FACT_CONTEXT).passed_checks is False
    assert ex.fact_7_1.passed_checks is True


def test_strict_types_refuse_a_count_written_as_text(ex):
    data = ex.document_accounting.to_json() | {"units_in": "48"}
    with pytest.raises(ValidationError) as exc_info:
        UnitAccounting.model_validate(data)
    assert _error_types(exc_info) == {"int_type"}


@pytest.mark.parametrize(
    ("name", "role", "error"),
    [
        ("", "Head of Compliance", "person.empty"),
        ("Dana Whitfield", "  ", "person.empty"),
        ("claude-sonnet-5-5", "Head of Compliance", "person.machine"),
        ("Claude Opus 5.5", "Head of Compliance", "person.machine"),
        ("system", "Head of Compliance", "person.machine"),
        ("Bot", "Head of Compliance", "person.machine"),
        (" claude ", "Head of Compliance", "person.machine"),
        ("GPT", "Head of Compliance", "person.machine"),
        ("Dana Whitfield", "System", "person.machine"),
        ("Dana Whitfield", "AI", "person.machine"),
    ],
)
def test_person_refuses_empty_values_and_whole_machine_identities(name, role, error):
    with pytest.raises(ValidationError) as exc_info:
        Person(name=name, role=role)
    assert _error_types(exc_info) == {error}


@pytest.mark.parametrize(
    ("name", "role"),
    [
        ("Claude Dupont", "Head of Compliance"),
        ("Ai Lin Tan", "Head of Model Risk"),
        ("Dana Whitfield", "Compliance Assistant"),
        ("Dana Whitfield", "Transfer Agent"),
        ("Dana Whitfield", "AI and Automation Lead"),
    ],
)
def test_person_accepts_names_and_roles_that_only_contain_a_machine_word(name, role):
    person = Person(name=name, role=role)
    assert (person.name, person.role) == (name, role)


def test_decision_answer_needs_a_question_subject(ex):
    with pytest.raises(ValidationError, match="only a question is"):
        Decision.on(
            ex.fact_7_1,
            outcome="answer",
            answer="Yes",
            reason="Because.",
            reviewer=REVIEWER,
            date="2026-11-25",
        )


def test_decision_amend_needs_the_amendment(ex):
    with pytest.raises(ValidationError, match="amend decision carries the amendment"):
        Decision.on(
            ex.fact_7_1,
            outcome="amend",
            reason="The deadline is incomplete.",
            reviewer=REVIEWER,
            date="2026-11-25",
        )


def test_decision_keeps_both_digests_of_its_subject(ex):
    assert ex.accept_7_1.seen_digest == record_digest(ex.fact_7_1)
    assert ex.accept_7_1.judged_digest == judged_digest(ex.fact_7_1)
    assert ex.accept_7_1.judged == ex.fact_7_1.judged_basis()


def test_decision_refuses_a_judged_digest_that_does_not_recompute(ex):
    fields = {k: v for k, v in ex.accept_7_1.to_json().items() if k not in {"id", "schema"}}
    with pytest.raises(ValidationError) as exc_info:
        Decision.build(**(fields | {"judged_digest": record_digest(ex.fact_7_1)}))
    assert _error_types(exc_info) == {"decision.judged-digest"}


def test_decision_date_must_be_in_the_calendar(ex):
    data = ex.accept_7_1.to_json() | {"date": "2026-13-01"}
    with pytest.raises(ValidationError) as exc_info:
        Decision.model_validate(data)
    assert _error_types(exc_info) == {"schema.date"}


def test_question_id_survives_a_change_of_state(ex):
    data = ex.question.to_json() | {"state": "answered", "decision_id": ex.answer.id}
    assert OpenQuestion.model_validate(data).id == ex.question.id


@pytest.mark.parametrize("state", ["answered", "accepted", "closed_no_answer"])
def test_question_settled_states_need_a_decision(ex, state):
    with pytest.raises(ValidationError, match=f"state {state} needs the person's decision"):
        OpenQuestion.model_validate(ex.question.to_json() | {"state": state})


def test_question_open_state_refuses_a_decision(ex):
    with pytest.raises(ValidationError, match="cannot carry a decision"):
        OpenQuestion.model_validate(ex.question.to_json() | {"decision_id": ex.answer.id})


def test_question_with_no_source_may_cite_nothing(ex):
    data = ex.question.to_json() | {"reason": "no_source", "cites": []}
    fields = {k: v for k, v in data.items() if k not in {"id", "schema"}}
    assert OpenQuestion.build(**fields).cites == []


def test_statement_refuses_no_cites_and_repeated_cites(ex):
    with pytest.raises(ValidationError, match="cites no fact"):
        Statement.build(text="A statement.", cites=[])
    with pytest.raises(ValidationError, match="cites a fact twice"):
        Statement.build(text="A statement.", cites=[ex.fact_7_1.id, ex.fact_7_1.id])


def test_brief_digest_changes_with_any_statement(ex):
    data = ex.brief.to_json()
    fields = {k: v for k, v in data.items() if k not in {"id", "schema", "content_digest"}}
    fields["statements"][0]["text"] += " Today."
    fields["statements"][0] = Statement.build(
        **{k: v for k, v in fields["statements"][0].items() if k != "id"}
    )
    changed = Brief.build(**fields)
    assert changed.content_digest != ex.brief.content_digest
    assert changed.id != ex.brief.id


def test_brief_digest_ignores_the_model_name(ex):
    fields = {
        k: v for k, v in ex.brief.to_json().items() if k not in {"id", "schema", "content_digest"}
    }
    assert (
        Brief.build(**(fields | {"model": "another-model"})).content_digest
        == ex.brief.content_digest
    )


def test_brief_id_is_the_start_of_its_digest(ex):
    assert ex.brief.id == "brief:" + ex.brief.content_digest.removeprefix("sha256:")[:16]


def test_signoff_returned_needs_a_reason_and_signed_refuses_one(ex):
    fields = {k: v for k, v in ex.sign_off.to_json().items() if k not in {"id", "schema"}}
    with pytest.raises(ValidationError, match="returned brief carries the reason"):
        SignOff.build(**(fields | {"outcome": "returned"}))
    with pytest.raises(ValidationError, match="returned brief carries the reason"):
        SignOff.build(**(fields | {"reason": "Fine."}))
    returned = SignOff.build(
        **(fields | {"outcome": "returned", "reason": "Paragraph 9.3 needs a date."})
    )
    assert returned.outcome == "returned"


def test_accounting_covers_all_48_paragraphs(ex):
    assert len(paragraph_anchors()) == 48
    accounting = ex.document_accounting
    assert len(accounting.with_facts) + len(accounting.without_facts) == accounting.units_in == 48


def test_accounting_refuses_a_unit_listed_twice(ex):
    data = ex.document_accounting.to_json()
    data["without_facts"].append({"anchor": "para:1.1", "reason": "Listed twice."})
    data["units_in"] = 49
    fields = {k: v for k, v in data.items() if k not in {"id", "schema"}}
    with pytest.raises(ValidationError, match="para:1.1"):
        UnitAccounting.build(**fields)


def test_extra_fields_are_refused_everywhere(ex):
    for record in vars(ex).values():
        context = FACT_CONTEXT if isinstance(record, Fact) else None
        with pytest.raises(ValidationError) as exc_info:
            type(record).model_validate(record.to_json() | {"approved": True}, context=context)
        assert _error_types(exc_info) == {"extra_forbidden"}


def test_records_are_immutable(ex):
    with pytest.raises(ValidationError, match="frozen"):
        ex.fact_7_1.quote = "changed"
