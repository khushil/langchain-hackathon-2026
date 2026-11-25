"""Tests of the second read: a marked paragraph left without a fact is read again, once, alone."""

import typing

import pytest
from engine_fakes import (
    DOCUMENT,
    Harness,
    ScriptedModels,
    default_summary,
    empty_second_read,
    obliging_second_read,
)

from context.accounting import NO_FACT_REASON, marked_no_fact_reason
from context.errors import AccountingError
from fsi_common.ids import canonical_json
from fsi_common.records import Brief, Fact, OpenQuestion, UnitAccounting
from sub_agent import SectionSummary
from utils.records import FACT_CONTEXT
from workflow.closing import close_run
from workflow.engine_state import EngineState
from workflow.errors import SectionCallError
from workflow.sections import make_section_step

REQUEST = {"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "x"}


def missing(*numbers: str):
    """A first read that, like the first whole-document run, finds nothing in these paragraphs."""

    def read(section):
        base = default_summary(section)
        kept = [o for o in base.obligations if o.paragraph not in numbers]
        return base.model_copy(update={"obligations": kept})

    return read


def _facts(values):
    return [
        Fact.model_validate(c, context=FACT_CONTEXT) for cs in values["facts"].values() for c in cs
    ]


def _questions(values):
    return [OpenQuestion.model_validate(q) for q in values["open_questions"].values()]


def _checks(values, name):
    return {v["subject_id"]: v for v in values["check_results"].values() if v["check"] == name}


def _document_accounting(values):
    document = next(s for s in values["sources"].values() if s["kind"] == "document")
    return UnitAccounting.model_validate(values["accounting"][document["id"]])


def test_a_marked_paragraph_left_without_a_fact_is_read_again_once_and_alone():
    models = ScriptedModels(section=missing("9.3"))
    Harness(models).start("9")
    assert models.rereads == ["9.3"]
    (task,) = models.reread_tasks
    assert task.startswith("Number: 9\nTitle: ")
    assert DOCUMENT.paragraph("para:9.3").text in task
    for other in ("9.1", "9.2", "9.4"):
        assert DOCUMENT.paragraph(f"para:{other}").text not in task


def test_the_second_read_is_asked_of_the_section_role_and_nothing_else_is_added_to_a_call():
    models = ScriptedModels(section=missing("9.3"))
    Harness(models).start("9")
    roles = [role for role, _ in models.calls]
    assert roles.count("section") == 2 and roles.count("brief") == 1


def test_a_paragraph_with_no_marker_gets_no_second_read():
    models = ScriptedModels()
    Harness(models).start("9")
    assert models.rereads == []
    assert len(models.calls) == 2


def test_a_second_read_that_finds_the_obligation_gives_a_fact_that_enters_as_any_other():
    models = ScriptedModels(section=missing("9.3"), paragraph=obliging_second_read)
    harness = Harness(models)
    values = harness.values(harness.start("9"))
    (fact,) = [f for f in _facts(values) if f.subject.anchor == "para:9.3"]
    assert fact.kind == "obligation" and fact.passed_checks
    assert [c.check for c in fact.checks] == ["quote-verbatim.v1", "deadline-verbatim.v1"]
    assert _questions(values) == []
    accounting = _document_accounting(values)
    assert "para:9.3" in accounting.with_facts
    assert {u.anchor for u in accounting.without_facts} == {"para:9.1", "para:9.2", "para:9.4"}
    brief = Brief.model_validate(values["draft_brief"])
    assert fact.id in {i for s in brief.statements for i in s.cites}
    assert _checks(values, "brief-covers-obligations.v1")[brief.id]["outcome"] == "pass"
    first = SectionSummary.model_validate(values["raw_summaries"]["9"])
    assert first == missing("9.3")(DOCUMENT.section("9"))
    assert list(values["second_reads"]) == ["para:9.3"]
    record = values["second_reads"]["para:9.3"]
    assert (record["section"], record["marker"]) == ("9", "must")
    assert DOCUMENT.paragraph("para:9.3").text in record["asked"]
    assert [o["paragraph"] for o in record["summary"]["obligations"]] == ["9.3"]
    assert record["gave_obligation"] is True
    assert (record["fact_ids"], record["open_question_id"]) == ([fact.id], None)


def test_a_second_read_that_finds_none_gives_an_open_question_naming_paragraph_and_marker():
    models = ScriptedModels(section=missing("9.3"), paragraph=empty_second_read)
    harness = Harness(models)
    values = harness.values(harness.start("9"))
    assert not [f for f in _facts(values) if f.subject.anchor == "para:9.3"]
    (question,) = _questions(values)
    assert question.about.anchor == "para:9.3"
    assert "paragraph 9.3" in question.question and '"must"' in question.question
    assert (question.reason, question.state) == ("ambiguous_meaning", "open")
    brief = Brief.model_validate(values["draft_brief"])
    assert brief.open_question_ids == [question.id]
    assert models.rereads == ["9.3"]
    record = values["second_reads"]["para:9.3"]
    assert record["summary"]["obligations"] == [] and record["gave_obligation"] is False
    assert (record["fact_ids"], record["open_question_id"]) == ([], question.id)
    assert SectionSummary.model_validate(values["raw_summaries"]["9"]).obligations == []


def test_a_run_with_no_second_read_holds_no_second_read_record():
    harness = Harness(ScriptedModels())
    values = harness.values(harness.start("9"))
    assert values.get("second_reads", {}) == {}


def test_the_accounting_reason_for_that_paragraph_names_the_marker_and_the_counts_close():
    models = ScriptedModels(section=missing("9.3"))
    harness = Harness(models)
    values = harness.values(harness.start("9"))
    accounting = _document_accounting(values)
    reasons = {u.anchor: u.reason for u in accounting.without_facts}
    assert reasons["para:9.3"] == marked_no_fact_reason("must")
    assert {reasons[a] for a in ("para:9.1", "para:9.2", "para:9.4")} == {NO_FACT_REASON}
    assert accounting.units_in == 4 and len(accounting.with_facts) + len(reasons) == 4
    line = _checks(values, "units-accounted.v1")[accounting.source_id]["detail"]
    assert line.startswith("PS26-4: 4 of 4 units accounted for (0 with facts, 4 without)")


def test_the_run_states_how_many_paragraphs_were_read_again_and_how_many_are_questions():
    models = ScriptedModels(section=missing("9.3"), paragraph=empty_second_read)
    harness = Harness(models)
    values = harness.values(harness.start("9"))
    detail = _checks(values, "marker-check.v1")["section:9"]["detail"]
    assert "1 of 1 paragraph(s) with an obligation marker were read a second time" in detail
    assert "9.3" in detail and "1 remain open questions" in detail
    models = ScriptedModels(section=missing("9.3"), paragraph=obliging_second_read)
    harness = Harness(models)
    detail = _checks(harness.values(harness.start("9")), "marker-check.v1")["section:9"]["detail"]
    assert "0 remain open questions" in detail
    quiet = Harness()
    detail = _checks(quiet.values(quiet.start("9")), "marker-check.v1")["section:9"]["detail"]
    assert detail.startswith("0 of 1 paragraph(s) with an obligation marker were read")


def test_a_second_read_that_gives_a_fact_failing_its_check_keeps_it_and_asks_about_the_paragraph():
    def lying(section, number):
        read = obliging_second_read(section, number)
        bad = read.obligations[0].model_copy(update={"evidence": "Firms ought to update contracts"})
        return read.model_copy(update={"obligations": [bad]})

    harness = Harness(ScriptedModels(section=missing("9.3"), paragraph=lying))
    values = harness.values(harness.start("9"))
    (fact,) = [f for f in _facts(values) if f.subject.anchor == "para:9.3"]
    assert not fact.passed_checks
    assert fact.id in values["facts"]
    (question,) = _questions(values)
    assert (question.about.anchor, question.reason) == ("para:9.3", "ambiguous_meaning")
    brief = Brief.model_validate(values["draft_brief"])
    assert fact.id not in {i for s in brief.statements for i in s.cites}


def test_a_second_read_that_cites_another_paragraph_leaves_the_marked_one_as_a_question():
    def elsewhere(section, number):
        read = obliging_second_read(section, number)
        moved = read.obligations[0].model_copy(update={"paragraph": "9.99"})
        return read.model_copy(update={"obligations": [moved]})

    models = ScriptedModels(section=missing("9.3"), paragraph=elsewhere)
    harness = Harness(models)
    values = harness.values(harness.start("9"))
    reasons = sorted((q.about.anchor, q.reason) for q in _questions(values))
    assert reasons == [("para:9.3", "ambiguous_meaning"), ("para:9.99", "unresolved_reference")]
    assert models.rereads == ["9.3"]


def test_every_marked_paragraph_left_without_a_fact_is_read_again_once_in_a_whole_run():
    left = ("2.4", "4.1", "5.3", "6.4", "8.2", "9.3")
    models = ScriptedModels(section=missing(*left), paragraph=obliging_second_read)
    harness = Harness(models)
    values = harness.values(harness.start())
    assert sorted(models.rereads, key=lambda n: tuple(map(int, n.split(".")))) == list(left)
    assert len(set(models.rereads)) == len(models.rereads) == 6
    accounting = _document_accounting(values)
    assert accounting.units_in == 48
    assert len(accounting.with_facts) + len(accounting.without_facts) == 48
    assert {"para:2.4", "para:9.3"} <= set(accounting.with_facts)
    assert _questions(values) == []


def test_second_reads_never_run_more_than_four_calls_at_once_with_the_section_reads():
    left = ("2.4", "4.1", "5.3", "6.4", "8.2", "9.3")
    models = ScriptedModels(section=missing(*left), delay=0.02)
    Harness(models).start()
    assert 1 < models.peak <= 4


def test_the_state_is_the_same_bytes_whichever_order_the_second_reads_finish_in():
    left = ("4.1", "5.3", "9.3")

    def run(delay):
        models = ScriptedModels(
            section=missing(*left), paragraph=empty_second_read, reread_delay=delay
        )
        harness = Harness(models)
        return harness.values(harness.start("4", "5", "9"))

    forward = run(lambda number: {"4.1": 0.0, "5.3": 0.05, "9.3": 0.1}[number])
    backward = run(lambda number: {"4.1": 0.1, "5.3": 0.05, "9.3": 0.0}[number])
    assert list(forward["second_reads"]) == ["para:4.1", "para:5.3", "para:9.3"]
    assert list(backward["second_reads"]) == ["para:4.1", "para:5.3", "para:9.3"]
    assert canonical_json(forward) == canonical_json(backward)


def test_section_writes_with_second_reads_folded_in_either_order_give_the_same_bytes():
    step = make_section_step(
        ScriptedModels(section=missing("4.1", "9.3"), paragraph=obliging_second_read)
    )
    writes = [step({"request": REQUEST, "section": n}) for n in ("4", "9", "10")]
    hints = typing.get_type_hints(EngineState, include_extras=True)

    def fold(order):
        state = {}
        for write in order:
            for key, value in write.items():
                state[key] = hints[key].__metadata__[0](state.get(key), value)
        return state

    assert canonical_json(fold(writes)) == canonical_json(fold(list(reversed(writes))))


def test_a_second_read_that_is_not_a_section_summary_is_refused_naming_the_paragraph():
    models = ScriptedModels(section=missing("9.3"), paragraph=lambda section, number: {"x": 1})
    with pytest.raises(SectionCallError, match=r"paragraph 9\.3"):
        Harness(models).start("9")


def test_closing_stops_naming_a_marked_paragraph_that_has_no_fact_and_no_question():
    harness = Harness(ScriptedModels(section=missing("9.3"), paragraph=empty_second_read))
    values = dict(harness.values(harness.start("9")))
    values["open_questions"] = {}
    with pytest.raises(AccountingError, match=r"9\.3.*must|must.*9\.3"):
        close_run(values)


def test_closing_accepts_a_marked_paragraph_whose_question_is_in_the_state():
    harness = Harness(ScriptedModels(section=missing("9.3"), paragraph=empty_second_read))
    values = harness.values(harness.start("9"))
    update = close_run(values)
    marker_line = update["check_results"]
    detail = next(v["detail"] for v in marker_line.values() if v["check"] == "markers-closed.v1")
    assert detail == (
        "1 of 1 paragraphs that hold an obligation marker have no obligation fact that passed "
        "its checks and are open questions; 0 have one"
    )
