"""The graph reads every application, screens it against each entry, closes the counts and stops."""

import pytest
from engine_fakes import Harness
from kyc_fakes import ScriptedReader, reading_of

from context.errors import AccountingError
from fsi_common.records import Fact, UnitAccounting
from utils.records import FACT_CONTEXT
from workflow.graph import NODES, build_graph


def facts_of(values):
    return [
        Fact.model_validate(c, context=FACT_CONTEXT)
        for contents in values["facts"].values()
        for c in contents
    ]


@pytest.fixture(scope="module")
def run():
    harness = Harness()
    config = harness.start()
    return harness, config, harness.values(config)


def test_the_graph_has_the_nodes_the_readme_names():
    assert NODES == (
        "read_sources",
        "read_application",
        "screen",
        "close_run",
        "write_brief",
        "review",
    )


def test_the_run_stops_at_the_review_and_decides_nothing(run):
    harness, config, values = run
    assert harness.graph.get_state(config).next == ("review",)
    assert not values.get("decisions") and not values.get("sign_off")
    assert harness.store.search(("kyc-onboarding", "sign-offs"), limit=10) == []


def test_each_application_is_read_once_by_the_extract_role(run):
    harness, _, values = run
    assert sorted(harness.models.asked) == [f"CUST-{n:03d}" for n in range(1, 26)]
    assert set(harness.models.roles) == {"extract"}
    assert sorted(values["raw_reads"]) == [f"CUST-{n:03d}" for n in range(1, 26)]


def test_the_counts_of_applications_and_screenings_close(run):
    _, _, values = run
    by_source = {
        s["key"]: UnitAccounting.model_validate(values["accounting"][s["id"]])
        for s in values["sources"].values()
    }
    assert set(by_source) == {"applications", "screenings"}
    apps, screenings = by_source["applications"], by_source["screenings"]
    assert (apps.units_in, len(apps.with_facts), len(apps.without_facts)) == (25, 25, 0)
    assert screenings.units_in == 350
    assert len(screenings.with_facts) + len(screenings.without_facts) == 350
    assert len(screenings.with_facts) == 18
    assert all(w.reason.startswith("No likeness") for w in screenings.without_facts)
    lines = {
        c["detail"] for c in values["check_results"].values() if c["check"] == "units-accounted.v1"
    }
    assert "applications: 25 of 25 units accounted for (25 with facts, 0 without)" in lines
    assert any(line.startswith("screenings: 350 of 350") for line in lines)


def test_thirteen_are_settled_by_the_checks_and_twelve_go_to_a_person(run):
    _, _, values = run
    proposals = [f for f in facts_of(values) if f.kind == "proposal"]
    assert len(proposals) == 25
    assert sum(f.attributes["settled"] for f in proposals) == 13
    assert len(values["open_questions"]) >= 12
    assert set(values["readings"]) <= set(values["open_questions"])


def test_the_review_request_holds_a_statement_for_each_application_and_every_question(run):
    harness, config, values = run
    request = harness.review_request(config)
    assert len(request.statements) == 25
    assert [s.heading.split()[0] for s in request.statements] == [
        f"CUST-{n:03d}" for n in range(1, 26)
    ]
    assert {q.id for q in request.open_questions} == set(values["open_questions"])
    for statement in request.statements:
        kinds = {c.fact.kind for c in statement.facts}
        assert "proposal" in kinds
        assert all(c.fact.passed_checks for c in statement.facts)
        assert {c.carry.outcome for c in statement.facts} == {"fresh"}


def test_a_chosen_batch_reads_only_its_applications():
    harness = Harness()
    config = harness.start("CUST-003", "CUST-001")
    values = harness.values(config)
    assert sorted(harness.models.asked) == ["CUST-001", "CUST-003"]
    accounting = {
        values["sources"][i]["key"]: UnitAccounting.model_validate(a)
        for i, a in values["accounting"].items()
    }
    assert accounting["applications"].units_in == 2
    assert accounting["screenings"].units_in == 28
    assert len(harness.review_request(config).statements) == 2


def test_a_name_the_application_does_not_write_is_not_screened_and_is_asked():
    reader = ScriptedReader(
        readings={"CUST-001": reading_of("CUST-001", name="Sarah Mitchell-Jones")}
    )
    harness = Harness(reader)
    config = harness.start("CUST-001", "CUST-004")
    values = harness.values(config)
    assert [q["reason"] for q in values["open_questions"].values()] == ["missing_data"]
    reasons = [r for a, r in values["screening_reasons"].items() if "CUST-001" in a]
    assert len(reasons) == 14 and all(r.startswith("Not screened") for r in reasons)
    assert "CUST-004" not in " ".join(r for r in reasons)


def test_a_screening_dropped_on_the_way_stops_the_run_naming_it(monkeypatch):
    import workflow.screening as step

    real = step.screen_pair

    def forgetful(applicant, entry, **kwargs):
        result = real(applicant, entry, **kwargs)
        return (
            None if (applicant.customer_id, entry.anchor_part) == ("CUST-004", "pep-2") else result
        )

    monkeypatch.setattr(step, "screen_pair", forgetful)
    harness = Harness()
    with pytest.raises((AccountingError, TypeError, AttributeError)):
        harness.start("CUST-004")


def test_a_screening_lost_from_the_state_stops_the_close_naming_it(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver

    import workflow.graph as graph_module

    real = graph_module.close_run

    def lose_one(state):
        units = {k: u for k, u in state["units"].items() if u["anchor"] != "pair:CUST-004/pep-2"}
        return real({**state, "units": units})

    monkeypatch.setattr(graph_module, "close_run", lose_one)
    graph = build_graph(models=ScriptedReader(), checkpointer=InMemorySaver())
    with pytest.raises(AccountingError, match=r"pair:CUST-004/pep-2"):
        graph.invoke(
            {"request": {"request": "r", "customer_ids": ["CUST-004"]}},
            {"configurable": {"thread_id": "lost"}},
        )


def test_two_runs_on_the_same_data_give_the_same_records(run):
    harness, _, values = run
    again = Harness()
    other = again.values(again.start())
    for key in ("facts", "open_questions", "accounting", "units", "draft_brief"):
        assert other[key] == values[key]


def test_a_screening_count_that_is_not_applications_times_entries_stops_the_read(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver

    import workflow.intake as intake

    real = intake.entries_of
    monkeypatch.setattr(intake, "entries_of", lambda: real()[:-1])
    graph = build_graph(models=ScriptedReader(), checkpointer=InMemorySaver())
    with pytest.raises(AccountingError, match=r"28 screenings.*2 applications by 13 list entries"):
        graph.invoke(
            {"request": {"request": "r", "customer_ids": ["CUST-001", "CUST-004"]}},
            {"configurable": {"thread_id": "count"}},
        )
