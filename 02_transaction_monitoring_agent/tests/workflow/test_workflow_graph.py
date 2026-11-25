"""The graph up to the review interrupt: read, assess, close the counts, write the brief."""

import pytest
from engine_fakes import Harness, ScriptedModels, bundle_of, label_script, request_for
from model_fakes import Assessment, assessment_for_score

from context.errors import AccountingError, CustomerNotFoundError, EmptyStreamError
from fsi_common.bundle_checks import check_bundle
from fsi_common.records import Brief, Fact
from utils.records import FACT_CONTEXT
from utils.state import OCT_19
from workflow.closing import close_run
from workflow.errors import AssessorPausedError
from workflow.graph import GRAPH_NAME, NODES, build_graph


def facts_of(values):
    return [Fact.model_validate(c, context=FACT_CONTEXT) for c in values["facts"].values()]


def checks_named(values, name):
    return {
        v["subject_id"]: v["detail"] for v in values["check_results"].values() if v["check"] == name
    }


def test_the_graph_has_five_steps_in_order_and_is_named():
    graph = build_graph()
    assert NODES == ("read_sources", "assess", "close_run", "write_brief", "review")
    assert set(graph.get_graph().nodes) >= {"__start__", *NODES}
    assert GRAPH_NAME == "transaction-monitoring" == graph.name


def test_a_whole_stream_is_assessed_one_transaction_at_a_time_and_stops_at_the_review():
    harness = Harness()
    config = harness.start("USR-001")
    values = harness.values(config)
    assert harness.graph.get_state(config).next == ("review",)
    assert harness.models.calls == [
        "TX-1001",
        "TX-1002",
        "TX-1003",
        "TX-1004",
        "TX-1005",
        "TX-1006",
        "TX-1007",
        "TX-1008",
        "TX-1009",
        "TX-1010",
    ]
    assert set(harness.models.roles) == {"assessor"}
    assert sorted(values["raw_assessments"]) == sorted(harness.models.calls)


def test_the_counts_close_ten_of_ten_transactions_and_one_of_one_profile():
    harness = Harness()
    values = harness.values(harness.start("USR-001"))
    lines = checks_named(values, "units-accounted.v1")
    assert sorted(lines.values()) == [
        "customer_profiles: 1 of 1 units accounted for (1 with facts, 0 without)",
        "transactions: 10 of 10 units accounted for (10 with facts, 0 without)",
    ]
    recorded = list(checks_named(values, "assessments-recorded.v1").values())
    assert recorded == [
        "10 of 10 transactions have an assessment that passed every check; 0 failed a check and "
        "0 have none"
    ]
    assert len(facts_of(values)) == 17


def test_the_starters_data_is_fifteen_transactions_over_two_runs_and_all_close():
    harness = Harness()
    totals = 0
    for user in ("USR-001", "USR-002"):
        values = harness.values(harness.start(user))
        accounting = [a for a in values["accounting"].values() if a["units_in"]]
        totals += sum(a["units_in"] for a in accounting)
        assert all(
            len(a["with_facts"]) + len(a["without_facts"]) == a["units_in"] for a in accounting
        )
    assert totals == 15 + 2


def test_a_window_reads_only_its_transactions():
    harness = Harness()
    before = harness.values(harness.start("USR-001", end=OCT_19))
    after = harness.values(harness.start("USR-001", start=OCT_19))
    assert sorted(before["raw_assessments"]) == [
        "TX-1001",
        "TX-1002",
        "TX-1003",
        "TX-1004",
        "TX-1005",
        "TX-1006",
    ]
    assert sorted(after["raw_assessments"]) == ["TX-1007", "TX-1008", "TX-1009", "TX-1010"]


def test_the_brief_has_a_statement_for_each_passing_assessment_citing_it_and_three_profile_facts():
    harness = Harness()
    values = harness.values(harness.start("USR-001", end=OCT_19))
    brief = Brief.model_validate(values["draft_brief"])
    by_id = {f.id: f for f in facts_of(values)}
    assert len(brief.statements) == 6
    for statement in brief.statements:
        kinds = sorted(by_id[c].kind for c in statement.cites)
        assert kinds == [
            "customer_attribute",
            "customer_attribute",
            "customer_attribute",
            "transaction_assessment",
        ]
        fields = {by_id[c].attributes.get("field") for c in statement.cites} - {None}
        assert fields == {"home_country", "currency", "usual_amount_range"}
    assert brief.open_question_ids == []
    assert brief.model == "claude-sonnet-5-5"
    assert brief.prompt_version.startswith("assessor-")


def test_a_statement_says_what_was_proposed_in_words_from_the_facts_alone():
    harness = Harness()
    values = harness.values(harness.start("USR-001", end="2026-10-10"))
    brief = Brief.model_validate(values["draft_brief"])
    third = next(s for s in brief.statements if "TX-1003" in s.text)
    assert third.text.startswith("TX-1003 at Hotel Miramar Lisboa, 380.0 GBP in PT (online)")
    assert "approve" in third.text and "45" in third.text and "0.5" in third.text
    assert third.heading == "9 October 2026"


def test_the_runs_records_pass_the_contracts_bundle_checks():
    harness = Harness()
    values = harness.values(harness.start("USR-001"))
    assert check_bundle(bundle_of(values), where="run") == []


def test_nothing_is_decided_before_a_person_does():
    harness = Harness()
    config = harness.start("USR-001")
    values = harness.values(config)
    assert not values.get("decisions") and not values.get("sign_off")
    from utils.review import decisions_namespace

    assert harness.store.search(decisions_namespace("USR-001"), limit=100) == []


def test_an_assessment_the_assessor_never_recorded_is_listed_and_asked_about():
    script = label_script() | {"TX-1002": None}
    harness = Harness(ScriptedModels(script))
    values = harness.values(harness.start("USR-001", end=OCT_19))
    brief = Brief.model_validate(values["draft_brief"])
    assert len(brief.statements) == 5
    accounting = next(a for a in values["accounting"].values() if a["units_in"] == 6)
    assert [(u["anchor"], "no assessment" in u["reason"]) for u in accounting["without_facts"]] == [
        ("tx:TX-1002", True)
    ]
    questions = [v for v in values["open_questions"].values()]
    assert [(q["about"]["anchor"], q["reason"]) for q in questions] == [
        ("tx:TX-1002", "missing_data")
    ]
    assert brief.open_question_ids == [questions[0]["id"]]
    assert list(checks_named(values, "assessments-recorded.v1").values()) == [
        "5 of 6 transactions have an assessment that passed every check; 0 failed a check and "
        "1 have none"
    ]
    assert check_bundle(bundle_of(values), where="run") == []


def test_an_assessment_that_fails_a_check_stays_a_fact_stays_off_the_brief_and_is_asked_about():
    script = label_script() | {"TX-1005": assessment_for_score(300, reason="Off the scale.")}
    harness = Harness(ScriptedModels(script))
    values = harness.values(harness.start("USR-001", end=OCT_19))
    brief = Brief.model_validate(values["draft_brief"])
    failed = [f for f in facts_of(values) if not f.passed_checks]
    assert [f.subject.anchor for f in failed] == ["tx:TX-1005"]
    assert all(failed[0].id not in s.cites for s in brief.statements)
    assert len(brief.statements) == 5
    accounting = next(a for a in values["accounting"].values() if a["units_in"] == 6)
    assert "tx:TX-1005" in accounting["with_facts"] and accounting["without_facts"] == []
    questions = list(values["open_questions"].values())
    assert [q["about"]["anchor"] for q in questions] == ["tx:TX-1005"]
    assert check_bundle(bundle_of(values), where="run") == []


def test_every_transaction_failing_or_missing_leaves_nothing_to_put_to_a_reviewer_and_stops():
    harness = Harness(ScriptedModels({}))
    from workflow.errors import NothingToReviewError

    with pytest.raises(NothingToReviewError, match="USR-001"):
        harness.start("USR-001")


def test_a_dropped_transaction_unit_stops_the_closing_and_names_it():
    harness = Harness()
    values = harness.values(harness.start("USR-001", end=OCT_19))
    units = dict(values["units"])
    dropped = next(k for k, u in units.items() if u["anchor"] == "tx:TX-1004")
    del units[dropped]
    with pytest.raises(AccountingError, match="tx:TX-1004") as caught:
        close_run({**values, "units": units})
    assert caught.value.missing == ["tx:TX-1004"]


def test_a_transaction_the_assessing_step_returned_nothing_for_stops_the_closing_and_names_it():
    harness = Harness()
    values = harness.values(harness.start("USR-001", end=OCT_19))
    raw = {k: v for k, v in values["raw_assessments"].items() if k != "TX-1006"}
    with pytest.raises(AccountingError, match="TX-1006"):
        close_run({**values, "raw_assessments": raw})


def test_an_unknown_customer_and_an_empty_window_stop_the_run_by_name():
    harness = Harness()
    with pytest.raises(CustomerNotFoundError, match="USR-404"):
        harness.graph.invoke(request_for("USR-404"), {"configurable": {"thread_id": "t-a"}})
    with pytest.raises(EmptyStreamError, match="USR-002"):
        harness.graph.invoke(
            request_for("USR-002", start="2026-11-01"), {"configurable": {"thread_id": "t-b"}}
        )


def test_records_for_a_transaction_outside_the_window_are_named_and_not_read():
    stray = Assessment(5, 0.9, "approve", "Recorded under another id.", record_as="TX-9999")
    harness = Harness(ScriptedModels(label_script() | {"TX-1002": stray}))
    values = harness.values(harness.start("USR-001", end=OCT_19))
    detail = list(checks_named(values, "assessments-read.v1").values())
    assert detail == [
        "5 of 6 transactions of USR-001 have a recorded assessment; records for TX-9999, which "
        "are not in the window, are not read"
    ]
    assert "tx:TX-1002" not in {f.subject.anchor for f in facts_of(values)}
    assert [q["about"]["anchor"] for q in values["open_questions"].values()] == ["tx:TX-1002"]


def test_a_tool_that_pauses_for_a_person_stops_the_run_and_names_the_transaction(monkeypatch):
    monkeypatch.setattr("workflow.assess.NEVER_ASK", 0.7)
    harness = Harness()
    with pytest.raises(AssessorPausedError, match="TX-1003"):
        harness.start("USR-001")
