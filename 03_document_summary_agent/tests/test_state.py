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
from fsi_common.records import record_digest
from utils.state import (
    BriefState,
    CitedFact,
    ConflictingWriteError,
    InvalidNamespaceLabelError,
    ReviewMismatchError,
    ReviewRequest,
    ReviewResponse,
    ReviewStatement,
    decisions_namespace,
    merge_records,
    merge_sections,
    sign_offs_namespace,
    update_records,
)


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


def _fan_out_graph():
    def split(state: BriefState):
        return [Send("read_section", {"number": str(n)}) for n in range(1, 11)]

    def read_section(item: dict):
        number = item["number"]
        return {
            "section_results": {number: {"number": number}},
            "facts": {f"fact:{number}": {"n": number}},
        }

    graph = StateGraph(BriefState)
    graph.add_node("read_section", read_section)
    graph.add_conditional_edges(START, split, ["read_section"])
    graph.add_edge("read_section", END)
    return graph.compile(checkpointer=InMemorySaver())


def test_ten_parallel_sections_give_ordered_deterministic_state():
    request = {"request": {"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "Summarise"}}
    outputs = []
    for thread in ("one", "two"):
        state = _fan_out_graph().invoke(request, {"configurable": {"thread_id": thread}})
        outputs.append(json.dumps({k: state[k] for k in ("section_results", "facts")}))
    assert outputs[0] == outputs[1]
    assert list(json.loads(outputs[0])["section_results"]) == [str(n) for n in range(1, 11)]


def test_state_survives_the_checkpointer_as_plain_json(ex, monkeypatch):
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    graph = StateGraph(BriefState)
    graph.add_node("write", lambda state: {"facts": {ex.fact_7_1.id: ex.fact_7_1.to_json()}})
    graph.add_edge(START, "write")
    graph.add_edge("write", END)
    saver = InMemorySaver()
    app = graph.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "t"}}
    app.invoke(
        {"request": {"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "r"}}, config
    )
    assert app.get_state(config).values["facts"][ex.fact_7_1.id] == ex.fact_7_1.to_json()


def _review_request(ex) -> ReviewRequest:
    statement = ex.brief.statements[0]
    cited = CitedFact(
        fact=ex.fact_7_1, seen_digest=record_digest(ex.fact_7_1), unit_text="7.1 Firms must ..."
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
    assert ReviewRequest.model_validate(payload) == request


def test_a_cited_fact_carries_its_own_digest(ex):
    with pytest.raises(ValidationError, match="seen_digest is not the digest"):
        CitedFact(
            fact=ex.fact_7_1, seen_digest=ex.brief.content_digest, unit_text="7.1 Firms must ..."
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
