"""Tests of the state's reducers, the review interrupt's payload and resume value, and the store."""

import json
import operator

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore
from langgraph.types import Send
from pydantic import ValidationError

from fsi_common.examples.data import REVIEWER, build_examples
from fsi_common.records import (
    Disagreement,
    Extractor,
    Fact,
    carry_over,
    judged_digest,
    record_digest,
)
from utils.records import FACT_CONTEXT
from utils.state import (
    BriefState,
    CitedFact,
    ConflictingWriteError,
    InvalidFactWriteError,
    InvalidNamespaceLabelError,
    ReviewMismatchError,
    ReviewRequest,
    ReviewResponse,
    ReviewStatement,
    decisions_namespace,
    fact_variants,
    fact_writes,
    merge_fact_variants,
    merge_records,
    merge_sections,
    sign_offs_namespace,
    update_records,
    variant_disagreements,
)

COMPARE = Extractor(name="fact-variants", version="0.1.0")


@pytest.fixture(scope="module")
def ex():
    return build_examples()


def test_merge_records_sorts_and_keeps_identical_writes():
    assert list(merge_records({"b": 1}, {"a": 2, "b": 1})) == ["a", "b"]


def test_merge_records_refuses_two_contents_under_one_id():
    with pytest.raises(ConflictingWriteError, match="fact:1"):
        merge_records({"fact:1": {"quote": "a"}}, {"fact:1": {"quote": "b"}})


def test_update_records_lets_a_question_move_on():
    assert update_records({"q": {"state": "open"}}, {"q": {"state": "answered"}}) == {
        "q": {"state": "answered"}
    }


def test_merge_sections_orders_sections_by_number():
    merged = merge_sections({"10": {}, "2": {}}, {"1": {}, "9": {}})
    assert list(merged) == ["1", "2", "9", "10"]


def test_merge_handles_a_missing_side():
    assert merge_records(None, {"a": 1}) == {"a": 1}
    assert merge_sections({"1": 1}, None) == {"1": 1}


def _section_fact(ex, number: str) -> Fact:
    fields = {k: v for k, v in ex.fact_7_1.to_json().items() if k not in {"id", "schema"}}
    anchor = f"para:{number}.1"
    fields["subject"] = fields["subject"] | {"anchor": anchor}
    fields["provenance"] = fields["provenance"] | {"anchor": anchor}
    return Fact.build(context=FACT_CONTEXT, **fields)


def _fan_out_graph(ex):
    facts = {str(n): _section_fact(ex, str(n)) for n in range(1, 11)}

    def split(state: BriefState):
        return [Send("read_section", {"number": str(n)}) for n in range(1, 11)]

    def read_section(item: dict):
        number = item["number"]
        return {
            "section_results": {number: {"number": number}},
            "facts": fact_writes([facts[number]]),
        }

    graph = StateGraph(BriefState)
    graph.add_node("read_section", read_section)
    graph.add_conditional_edges(START, split, ["read_section"])
    graph.add_edge("read_section", END)
    return graph.compile(checkpointer=InMemorySaver())


def test_ten_parallel_sections_give_ordered_deterministic_state(ex):
    request = {"request": {"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "Summarise"}}
    outputs = []
    for thread in ("one", "two"):
        state = _fan_out_graph(ex).invoke(request, {"configurable": {"thread_id": thread}})
        outputs.append(json.dumps({k: state[k] for k in ("section_results", "facts")}))
    assert outputs[0] == outputs[1]
    assert list(json.loads(outputs[0])["section_results"]) == [str(n) for n in range(1, 11)]


def test_state_survives_the_checkpointer_as_plain_json(ex, monkeypatch):
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    graph = StateGraph(BriefState)
    graph.add_node("write", lambda state: {"facts": fact_writes([ex.fact_7_1])})
    graph.add_edge(START, "write")
    graph.add_edge("write", END)
    saver = InMemorySaver()
    app = graph.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "t"}}
    app.invoke(
        {"request": {"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "r"}}, config
    )
    assert app.get_state(config).values["facts"][ex.fact_7_1.id] == [ex.fact_7_1.to_json()]


def _two_readers_graph(first, second):
    def split(state: BriefState):
        return [Send("read", {"fact": first}), Send("read", {"fact": second})]

    graph = StateGraph(BriefState)
    graph.add_node("read", lambda item: {"facts": {item["fact"]["id"]: [item["fact"]]}})
    graph.add_conditional_edges(START, split, ["read"])
    graph.add_edge("read", END)
    return graph.compile(checkpointer=InMemorySaver())


def test_two_contents_under_one_fact_id_are_both_kept_without_an_exception(ex):
    first, second = ex.fact_7_1.to_json(), ex.fact_7_1_variant.to_json()
    assert first["id"] == second["id"] and first != second
    request = {"request": {"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "r"}}
    state = _two_readers_graph(first, second).invoke(
        request, {"configurable": {"thread_id": "variants"}}
    )
    kept = state["facts"][ex.fact_7_1.id]
    assert len(kept) == 2
    assert {json.dumps(c, sort_keys=True) for c in kept} == {
        json.dumps(first, sort_keys=True),
        json.dumps(second, sort_keys=True),
    }


def test_fact_variants_are_kept_in_one_order_whatever_the_order_of_writes(ex):
    a, b = fact_writes([ex.fact_7_1]), fact_writes([ex.fact_7_1_variant])
    assert merge_fact_variants(a, b) == merge_fact_variants(b, a)
    assert merge_fact_variants(a, a) == a
    assert fact_variants(a) == {}
    assert list(fact_variants(merge_fact_variants(a, b))) == [ex.fact_7_1.id]


def test_variants_become_one_disagreement_the_validator_accepts(ex):
    facts = merge_fact_variants(fact_writes([ex.fact_7_1]), fact_writes([ex.fact_7_1_variant]))
    [found] = variant_disagreements(facts, found_by=COMPARE)
    assert {(c.fact_id, c.judged_digest) for c in found.claims} == {
        (ex.fact_7_1.id, judged_digest(ex.fact_7_1)),
        (ex.fact_7_1.id, judged_digest(ex.fact_7_1_variant)),
    }
    assert "attributes.requirement" in found.about
    assert Disagreement.model_validate(found.to_json()) == found
    expected = ex.variant_disagreement
    assert (found.claims, found.found_by, found.status) == (
        expected.claims,
        expected.found_by,
        expected.status,
    )


def test_contents_differing_only_outside_what_is_judged_keep_one_fixed_copy(ex):
    a, b = fact_writes([ex.fact_7_1]), fact_writes([ex.fact_7_1_rerun])
    lowest = min((ex.fact_7_1, ex.fact_7_1_rerun), key=record_digest).to_json()
    for first, second in ((a, b), (b, a)):
        facts = merge_fact_variants(first, second)
        assert facts == {ex.fact_7_1.id: [lowest]}
        assert variant_disagreements(facts, found_by=COMPARE) == []


def test_parallel_writers_of_one_judged_fact_leave_one_copy_in_any_order(ex):
    first, second = ex.fact_7_1.to_json(), ex.fact_7_1_rerun.to_json()
    lowest = min((ex.fact_7_1, ex.fact_7_1_rerun), key=record_digest).to_json()
    request = {"request": {"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "r"}}
    for order, (x, y) in enumerate(((first, second), (second, first))):
        state = _two_readers_graph(x, y).invoke(
            request, {"configurable": {"thread_id": f"one-copy-{order}"}}
        )
        assert state["facts"] == {ex.fact_7_1.id: [lowest]}


def test_a_content_that_is_not_fact_json_is_refused():
    with pytest.raises(InvalidFactWriteError, match="is not fact JSON"):
        merge_fact_variants(None, {"fact:1": [{"n": "1"}]})


def test_facts_written_as_a_bare_record_are_refused(ex):
    with pytest.raises(InvalidFactWriteError, match="write \\{fact id"):
        merge_fact_variants(None, {ex.fact_7_1.id: ex.fact_7_1.to_json()})


def _review_request(ex) -> ReviewRequest:
    statement = ex.brief.statements[0]
    cited = CitedFact(
        fact=ex.fact_7_1,
        seen_digest=record_digest(ex.fact_7_1),
        unit_text="7.1 Firms must ...",
        carry=carry_over(None, ex.fact_7_1),
    )
    return ReviewRequest(
        brief_id=ex.brief.id,
        brief_digest=ex.brief.content_digest,
        request=ex.brief.request,
        statements=[
            ReviewStatement(
                statement_id=statement.id,
                heading=statement.heading,
                text=statement.text,
                facts=[cited],
            )
        ],
        open_questions=[ex.question],
    )


def test_the_review_payload_is_json_and_reads_back(ex):
    request = _review_request(ex)
    payload = request.to_payload()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["statements"][0]["facts"][0]["fact"]["schema"] == "fact.v1"
    assert ReviewRequest.model_validate(payload, context=FACT_CONTEXT) == request


def test_a_cited_fact_carries_its_own_digest(ex):
    with pytest.raises(ValidationError, match="seen_digest is not the digest"):
        CitedFact(
            fact=ex.fact_7_1,
            seen_digest=ex.brief.content_digest,
            unit_text="7.1 Firms must ...",
            carry=carry_over(None, ex.fact_7_1),
        )


@pytest.mark.parametrize(
    ("fact_name", "with_decision", "outcome", "differences"),
    [
        ("fact_7_1_rerun", True, "carried", []),
        ("fact_7_1_variant", True, "ask_again", ["attributes.requirement"]),
        ("fact_7_1", False, "fresh", []),
    ],
)
def test_the_review_payload_carries_each_facts_earlier_decision(
    ex, fact_name, with_decision, outcome, differences
):
    fact = getattr(ex, fact_name)
    earlier = ex.accept_7_1 if with_decision else None
    cited = CitedFact(
        fact=fact,
        seen_digest=record_digest(fact),
        unit_text="7.1 Firms must ...",
        carry=carry_over(earlier, fact),
    )
    request = _review_request(ex).model_copy(
        update={
            "statements": [_review_request(ex).statements[0].model_copy(update={"facts": [cited]})]
        }
    )
    payload = request.to_payload()
    carry = payload["statements"][0]["facts"][0]["carry"]
    assert carry["outcome"] == outcome
    assert carry["differences"] == differences
    if with_decision:
        assert carry["decision"]["id"] == ex.accept_7_1.id
        assert carry["decision"]["reviewer"] == REVIEWER
        assert carry["decision"]["date"] == ex.accept_7_1.date
    else:
        assert carry["decision"] is None
    assert ReviewRequest.model_validate(payload, context=FACT_CONTEXT) == request


def test_a_rerun_fact_is_shown_with_its_carried_decision(ex):
    cited = CitedFact(
        fact=ex.fact_7_1_rerun,
        seen_digest=record_digest(ex.fact_7_1_rerun),
        unit_text="7.1 Firms must ...",
        carry=carry_over(ex.accept_7_1, ex.fact_7_1_rerun),
    )
    assert cited.carry.outcome == "carried"
    assert (cited.carry.decision.reviewer, cited.carry.decision.date) == (
        ex.accept_7_1.reviewer,
        ex.accept_7_1.date,
    )


def test_a_cited_fact_whose_carry_is_not_carry_over_is_refused(ex):
    with pytest.raises(ValidationError, match="carry is not what carry_over gives"):
        CitedFact(
            fact=ex.fact_7_1_variant,
            seen_digest=record_digest(ex.fact_7_1_variant),
            unit_text="7.1 Firms must ...",
            carry=carry_over(ex.accept_7_1, ex.fact_7_1),
        )


def test_the_resume_value_carries_one_reviewer(ex):
    response = ReviewResponse(reviewer=REVIEWER, decisions=[ex.accept_7_1], sign_off=ex.sign_off)
    response.check_against(_review_request(ex))
    assert (
        ReviewResponse.model_validate(response.model_dump(mode="json", by_alias=True)) == response
    )


def test_the_resume_value_refuses_another_persons_decision(ex):
    with pytest.raises(ValidationError, match="the reviewer's own"):
        ReviewResponse(
            reviewer={"name": "Sam Okafor", "role": "Compliance Analyst"}, decisions=[ex.accept_7_1]
        )


def test_the_resume_value_refuses_a_machine_reviewer():
    with pytest.raises(ValidationError, match="person.machine|names a model"):
        ReviewResponse(reviewer={"name": "Claude", "role": "Reviewer"}, decisions=[])


def test_a_sign_off_for_another_digest_is_refused(ex):
    response = ReviewResponse(reviewer=REVIEWER, decisions=[], sign_off=ex.sign_off)
    request = _review_request(ex).model_copy(update={"brief_digest": record_digest(ex.fact_7_1)})
    with pytest.raises(ReviewMismatchError, match="not for the brief and digest"):
        response.check_against(request)


def test_decisions_are_found_again_under_the_same_firm_and_document(ex):
    store = InMemoryStore()
    store.put(decisions_namespace("FIRM-001", "PS26-4"), ex.accept_7_1.id, ex.accept_7_1.to_json())
    found = store.search(decisions_namespace("FIRM-001", "PS26-4"))
    assert [item.value for item in found] == [ex.accept_7_1.to_json()]
    assert store.search(decisions_namespace("FIRM-002", "PS26-4")) == []


def test_namespaces_refuse_labels_the_store_cannot_hold():
    with pytest.raises(InvalidNamespaceLabelError, match="'PS26.4'"):
        decisions_namespace("FIRM-001", "PS26.4")
    with pytest.raises(InvalidNamespaceLabelError):
        sign_offs_namespace("", "PS26-4")
    assert sign_offs_namespace("FIRM-001", "PS26-4") == (
        "compliance-brief",
        "sign-offs",
        "FIRM-001",
        "PS26-4",
    )


def test_reducers_are_associative_for_disjoint_writes():
    a, b, c = {"x": 1}, {"y": 2}, {"z": 3}
    assert merge_records(merge_records(a, b), c) == merge_records(a, merge_records(b, c))
    assert operator.eq(list(merge_records(c, a)), ["x", "z"])
