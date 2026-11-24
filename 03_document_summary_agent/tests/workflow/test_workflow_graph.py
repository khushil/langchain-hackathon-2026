"""Tests of the graph up to the review interrupt: sections, accounting, facts and the brief."""

import typing

import pytest
from engine_fakes import (
    DOCUMENT,
    Harness,
    ScriptedModels,
    bundle_records,
    default_brief,
    default_summary,
    ghost_summary,
)

from context.errors import AccountingError
from fsi_common.bundle_checks import check_bundle
from fsi_common.ids import canonical_json
from fsi_common.records import Brief, Fact
from sub_agent import SectionSummary
from utils.records import FACT_CONTEXT, SectionResult, records_to_section_summary
from workflow.briefing import BriefDraft, DraftStatement
from workflow.engine_state import EngineState
from workflow.errors import (
    BriefCitationError,
    InvalidRequestError,
    SectionCallError,
    UnknownSectionError,
)
from workflow.graph import NODES, build_graph
from workflow.requests import selected_sections
from workflow.sections import make_section_step


def _checks(values, name):
    return {v["subject_id"]: v for v in values["check_results"].values() if v["check"] == name}


def _facts(values):
    return [
        Fact.model_validate(c, context=FACT_CONTEXT) for cs in values["facts"].values() for c in cs
    ]


def test_graph_nodes_are_the_five_steps_in_order_and_the_graph_is_named():
    graph = build_graph()
    assert NODES == ("read_sources", "section", "close_run", "write_brief", "review")
    assert set(graph.get_graph().nodes) >= {"__start__", *NODES}
    assert graph.name == "compliance-brief"


def test_a_full_run_reads_ten_sections_and_accounts_for_forty_eight_paragraphs():
    harness = Harness()
    config = harness.start()
    values = harness.values(config)
    assert harness.graph.get_state(config).next == ("review",)
    assert sorted(values["section_results"], key=int) == [str(n) for n in range(1, 11)]
    assert sorted(values["raw_summaries"], key=int) == [str(n) for n in range(1, 11)]
    document = next(s for s in values["sources"].values() if s["kind"] == "document")
    accounting = values["accounting"][document["id"]]
    assert (
        accounting["units_in"],
        len(accounting["with_facts"]) + len(accounting["without_facts"]),
    ) == (48, 48)
    line = _checks(values, "units-accounted.v1")[document["id"]]["detail"]
    assert line.startswith("PS26-4: 48 of 48 units accounted for (")
    assert _checks(values, "sections-selected.v1")[document["id"]]["detail"].startswith(
        "10 of 10 sections selected"
    )
    assert len(harness.models.calls) == 11
    assert sorted(role for role, _ in harness.models.calls) == ["brief"] + ["section"] * 10


def test_a_run_filtered_to_section_seven_accounts_for_five_of_five():
    harness = Harness()
    config = harness.start("7")
    values = harness.values(config)
    document = next(s for s in values["sources"].values() if s["kind"] == "document")
    assert list(values["section_results"]) == ["7"]
    assert _checks(values, "units-accounted.v1")[document["id"]]["detail"].startswith(
        "PS26-4: 5 of 5 units accounted for ("
    )
    assert sorted(
        u["anchor"] for u in values["units"].values() if u["anchor"].startswith("para:")
    ) == [
        "para:7.1",
        "para:7.2",
        "para:7.3",
        "para:7.4",
        "para:7.5",
    ]
    assert [c for r, c in harness.models.calls if r == "section"] == ["Number: 7"]


def test_the_raw_summary_of_each_section_is_what_the_model_returned():
    harness = Harness()
    values = harness.values(harness.start("7"))
    expected = default_summary(DOCUMENT.section("7")).model_dump(mode="json")
    assert values["raw_summaries"]["7"] == expected
    assert SectionSummary.model_validate(values["raw_summaries"]["7"]).number == "7"


def test_section_calls_never_exceed_four_at_once():
    models = ScriptedModels(delay=0.03)
    harness = Harness(models)
    harness.start()
    assert 1 < models.peak <= 4


def test_two_runs_with_the_same_inputs_give_the_same_state_bytes():
    harness_a, harness_b = Harness(), Harness()
    a = harness_a.values(harness_a.start("7", "9"))
    b = harness_b.values(harness_b.start("7", "9"))
    assert canonical_json(a) == canonical_json(b)


def test_a_failed_fact_stays_on_the_record_and_the_brief_never_cites_it():
    def summary(section):
        base = default_summary(section)
        if section.number != "7":
            return base
        bad = base.obligations[0].model_copy(
            update={"evidence": "Firms ought to tell the FSOA soon"}
        )
        return base.model_copy(update={"obligations": [bad, *base.obligations[1:]]})

    harness = Harness(ScriptedModels(section=summary))
    values = harness.values(harness.start("7"))
    failed = [f for f in _facts(values) if not f.passed_checks]
    assert len(failed) == 1
    brief = Brief.model_validate(values["draft_brief"])
    cited = {i for s in brief.statements for i in s.cites}
    assert failed[0].id not in cited
    assert failed[0].id in values["facts"]
    document = next(s for s in values["sources"].values() if s["kind"] == "document")
    assert "1 failed" in _checks(values, "facts-checked.v1")[document["id"]]["detail"]
    assert (
        "0 of 3 distinct facts failed"
        not in _checks(values, "section-read.v1")["section:7"]["detail"]
    )
    assert (
        "1 of 3 distinct facts failed" in _checks(values, "section-read.v1")["section:7"]["detail"]
    )


def test_an_obligation_citing_a_paragraph_that_does_not_exist_is_an_open_question_and_no_fact():
    def summary(section):
        base = default_summary(section)
        ghost = base.obligations[0].model_copy(update={"paragraph": "7.9"})
        return base.model_copy(update={"obligations": [*base.obligations, ghost]})

    harness = Harness(ScriptedModels(section=summary))
    config = harness.start("7")
    values = harness.values(config)
    (question,) = values["open_questions"].values()
    assert question["reason"] == "unresolved_reference" and question["state"] == "open"
    assert "7.9" in question["question"]
    assert summary(DOCUMENT.section("7")).obligations[-1].evidence in question["question"]
    assert not [f for f in _facts(values) if f.subject.anchor == "para:7.9"]
    real = len(default_summary(DOCUMENT.section("7")).obligations)
    assert len(values["raw_summaries"]["7"]["obligations"]) == real + 1
    assert len(values["section_results"]["7"]["fact_ids"]) == real
    check = _checks(values, "section-read.v1")["section:7"]
    assert check["outcome"] == "pass"
    assert f"{real} of {real} obligations" in check["detail"]
    assert "1 cite a paragraph" in check["detail"]
    brief = Brief.model_validate(values["draft_brief"])
    assert brief.open_question_ids == [question["id"]]
    request = harness.review_request(config)
    assert [q.id for q in request.open_questions] == [question["id"]]
    assert check_bundle(bundle_records(values), where="state") == []


def _twin_summary(section):
    base = default_summary(section)
    first = base.obligations[0]
    twin = first.model_copy(update={"requirement": "A second duty with the same quote"})
    return base.model_copy(update={"obligations": [*base.obligations, twin]})


def test_two_duties_with_one_quote_both_reach_the_state_the_brief_and_the_converted_summary():
    captured = {}

    def brief(task):
        captured["task"] = task
        return default_brief(task)

    harness = Harness(ScriptedModels(section=_twin_summary, brief=brief))
    values = harness.values(harness.start("7"))
    raw = SectionSummary.model_validate(values["raw_summaries"]["7"])
    real = len(default_summary(DOCUMENT.section("7")).obligations) + 1
    assert len(raw.obligations) == real
    requirements = [
        r for f in _facts(values) if f.kind == "obligation" for r in f.attributes["requirement"]
    ]
    assert sorted(requirements) == sorted(o.requirement for o in raw.obligations)
    obligation_facts = [f for f in _facts(values) if f.kind == "obligation"]
    assert all(isinstance(f.attributes["requirement"], list) for f in obligation_facts)
    assert "A second duty with the same quote" in captured["task"]
    assert "Duty from paragraph 7.1" in captured["task"]
    result = SectionResult.model_validate(values["section_results"]["7"])
    facts = {f.id: f for f in _facts(values)}
    assert len(result.fact_ids) == real
    assert records_to_section_summary(result, facts) == raw
    check = _checks(values, "section-read.v1")["section:7"]
    assert check["outcome"] == "pass" and f"{real} of {real} obligations" in check["detail"]


def test_section_read_fails_naming_the_paragraph_when_a_requirement_goes_missing(monkeypatch):
    import utils.records as records

    real = records.obligation_to_fact

    def forgetful(obligation, **kwargs):
        kwargs.pop("requirements", None)
        return real(obligation, **kwargs)

    monkeypatch.setattr(records, "obligation_to_fact", forgetful)
    harness = Harness(ScriptedModels(section=_twin_summary))
    values = harness.values(harness.start("7"))
    check = _checks(values, "section-read.v1")["section:7"]
    assert check["outcome"] == "fail"
    assert "7.1" in check["detail"]


def test_section_writes_folded_through_the_reducers_in_either_order_give_the_same_bytes():
    step = make_section_step(ScriptedModels(section=ghost_summary))
    request = {"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "x"}
    writes = [step({"request": request, "section": n}) for n in ("7", "9", "10")]
    hints = typing.get_type_hints(EngineState, include_extras=True)

    def fold(order):
        state = {}
        for write in order:
            for key, value in write.items():
                reducer = hints[key].__metadata__[0]
                state[key] = reducer(state.get(key), value)
        return state

    forward, backward = fold(writes), fold(list(reversed(writes)))
    assert canonical_json(forward) == canonical_json(backward)
    for key in forward:
        assert list(forward[key]) == list(backward[key]), key


def test_closing_stops_when_a_requested_section_never_reported(monkeypatch):
    import workflow.intake as intake

    real = intake.send_sections
    monkeypatch.setattr(
        "workflow.graph.send_sections",
        lambda state: [s for s in real(state) if s.arg["section"] != "9"],
    )
    with pytest.raises(AccountingError, match="9"):
        Harness().start("7", "9")


def test_a_brief_statement_citing_an_id_that_is_no_fact_stops_the_step_naming_it():
    ghost = "fact:0000000000000000"

    def citing_ghost(task):
        return BriefDraft(statements=[DraftStatement(text="x", cites=[ghost])])

    harness = Harness(ScriptedModels(brief=citing_ghost))
    with pytest.raises(BriefCitationError, match=ghost) as caught:
        harness.start("7")
    assert caught.value.fact_ids == [ghost]


def test_a_brief_statement_citing_the_id_of_a_failed_fact_is_refused():
    captured = {}

    def summary(section):
        base = default_summary(section)
        bad = base.obligations[0].model_copy(
            update={"evidence": "Firms ought to tell the FSOA soon"}
        )
        return base.model_copy(update={"obligations": [bad]})

    def cite_failed(task):
        failed_id = captured["failed"]
        return BriefDraft(statements=[DraftStatement(text="x", cites=[failed_id])])

    # Learn the failed fact's id from a first run, then script a brief that cites it.
    probe = Harness(ScriptedModels(section=summary))
    values = probe.values(probe.start("7"))
    captured["failed"] = next(f.id for f in _facts(values) if not f.passed_checks)
    harness = Harness(ScriptedModels(section=summary, brief=cite_failed))
    with pytest.raises(BriefCitationError, match="did not pass its checks"):
        harness.start("7")


def test_an_unknown_section_in_the_request_is_named():
    with pytest.raises(UnknownSectionError, match="11"):
        Harness().start("7", "11")


def test_a_failing_section_call_stops_the_run_and_names_the_section():
    harness = Harness(ScriptedModels(fail_sections=("3",)))
    with pytest.raises(RuntimeError, match="section 3"):
        harness.start()


def test_a_reply_that_is_not_a_section_summary_is_refused():
    harness = Harness(ScriptedModels(section=lambda section: {"number": 7}))
    with pytest.raises(SectionCallError, match="section 7"):
        harness.start("7")


def test_a_unit_dropped_between_reading_and_closing_stops_the_run_naming_it(monkeypatch):
    import workflow.intake as intake

    real = intake.read_sources

    def dropping(state):
        update = real(state)
        gone = next(k for k, u in update["units"].items() if u["anchor"] == "para:7.4")
        update["units"] = {k: v for k, v in update["units"].items() if k != gone}
        return update

    monkeypatch.setattr("workflow.graph.read_sources", dropping)
    harness = Harness()
    with pytest.raises(AccountingError, match=r"para:7\.4"):
        harness.start("7")


def test_a_model_that_mislabels_a_section_is_recorded_and_the_section_as_read_is_used():
    def summary(section):
        return default_summary(section).model_copy(update={"number": "8"})

    harness = Harness(ScriptedModels(section=summary))
    values = harness.values(harness.start("7"))
    check = _checks(values, "section-label.v1")["section:7"]
    assert check["outcome"] == "fail"
    assert list(values["section_results"]) == ["7"]
    assert values["raw_summaries"]["7"]["number"] == "8"


def test_default_brief_cites_every_obligation_so_coverage_passes():
    harness = Harness()
    values = harness.values(harness.start("7"))
    check = next(iter(_checks(values, "brief-covers-obligations.v1").values()))
    assert check["outcome"] == "pass"


def test_an_empty_section_list_is_refused_where_the_graph_reads_the_request():
    with pytest.raises(InvalidRequestError, match="sections"):
        selected_sections(DOCUMENT, {"sections": []})
    assert len(selected_sections(DOCUMENT, {})) == 10
