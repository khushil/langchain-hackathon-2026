"""The starter's agent runs on get_model: a recording replays, and a missing one stops it."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from model_fakes import ScriptedRunner, assessment_for_score

from agent import build_agent
from fsi_common.model import ChatClaudeHeadless, ReplayMissError, call_records, reset_call_records
from utils.models import ROLE_MODELS
from utils.state import MyAgentContext
from utils.transaction_processing import decision_log, transaction_message

SCRIPT = {
    "TX-1001": assessment_for_score(5, confidence=0.9, reason="A small grocery shop at home.")
}
ASSESSOR = ROLE_MODELS["assessor"]


def run_one(agent, tx="TX-1001", user="USR-001"):
    config = {"configurable": {"thread_id": user}}
    return agent.invoke(transaction_message(tx), config, context=MyAgentContext(user_id=user))


def recording_model(folder):
    return ChatClaudeHeadless(
        model=ASSESSOR.model,
        effort=ASSESSOR.effort,
        mode="record",
        recordings_dir=folder,
        runner=ScriptedRunner(SCRIPT),
    )


def test_a_recorded_run_replays_to_the_same_answer_and_the_same_audit_record(model_env, tmp_path):
    recorded = build_agent(
        model=recording_model(tmp_path), checkpointer=InMemorySaver(), store=InMemoryStore()
    )
    first = run_one(recorded)
    audit = decision_log(recorded, "USR-001")
    saved = sorted(p.name for p in tmp_path.glob("*.json"))
    assert len(saved) == 3

    model_env.setenv("MODEL_BACKEND", "replay")
    model_env.setenv("MODEL_RECORDINGS_DIR", str(tmp_path))
    reset_call_records()
    replayed = build_agent(checkpointer=InMemorySaver(), store=InMemoryStore())
    second = run_one(replayed)

    assert second["messages"][-1].text == first["messages"][-1].text == "Looked at TX-1001."
    assert decision_log(replayed, "USR-001") == audit
    assert audit[0]["risk_score"] == 5
    assert audit[0]["decided_by"] == "agent"
    assert {record.mode for record in call_records()} == {"replay"}
    assert len(call_records()) == 3


def test_a_missing_recording_stops_the_agent_by_name(model_env, tmp_path):
    model_env.setenv("MODEL_BACKEND", "replay")
    model_env.setenv("MODEL_RECORDINGS_DIR", str(tmp_path))
    agent = build_agent(checkpointer=InMemorySaver(), store=InMemoryStore())
    with pytest.raises(ReplayMissError, match="no recording"):
        run_one(agent)


def test_the_agent_reads_the_starters_prompt_and_the_three_tools(model_env):
    agent = build_agent()
    nodes = set(agent.get_graph().nodes)
    assert {"model", "tools"} <= nodes
