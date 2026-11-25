"""The starter's own graph runs on get_model: on a scripted model, and by name on no recording."""

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from model_fakes import FakeChatModel

import agent as starter
from utils import PROJECT_ROOT, nodes
from utils.nodes import CustomerProfile

PROFILES = {
    "Sarah Mitchell": CustomerProfile(
        full_name="Sarah Mitchell",
        date_of_birth="1990-03-14",
        nationality="British",
        occupation="software engineer",
        source_of_funds="salary",
    ),
    "Dmitri Volkonsky": CustomerProfile(
        full_name="Dmitri Volkonsky",
        date_of_birth="1975-09-11",
        nationality="Karvonian",
        occupation="director of a commodities trading firm",
        source_of_funds="business profits",
    ),
}


class ScriptedModel(FakeChatModel):
    """Reads a profile from the application text the prompt holds, and writes a fixed memo."""

    def with_structured_output(self, schema, **kwargs):
        self.structured = (schema, kwargs)

        def read(prompt):
            for name, profile in PROFILES.items():
                if name in str(prompt):
                    return profile
            raise AssertionError(f"no scripted profile for {prompt!r}")

        return RunnableLambda(read)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        result.generations[0].message = AIMessage(content=self.reply)
        return result


@pytest.fixture()
def roles(monkeypatch):
    """Replace get_model in the nodes with a scripted model, and list the roles asked for."""
    asked = []

    def get_model(role):
        asked.append(role)
        return ScriptedModel(calls=[], reply="Memo for the audit file.")

    monkeypatch.setattr(nodes, "get_model", get_model)
    return asked


def test_a_clean_application_is_approved_without_a_person(roles):
    graph = starter.build_agent(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t-clean"}}
    state = graph.invoke({"customer_id": "CUST-001"}, config)
    outcome = (state["risk_level"], state["decision"], state["reviewer"])
    assert outcome == ("low", "approve", "system")
    assert roles == ["extract", "memo"]
    assert "__interrupt__" not in state


def test_a_hit_pauses_for_a_person_and_resumes_with_their_answer(roles):
    graph = starter.build_agent(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t-hit"}}
    paused = graph.invoke({"customer_id": "CUST-003"}, config)
    assert paused["__interrupt__"][0].value["customer"] == "Dmitri Volkonsky"
    answer = {"decision": "reject", "notes": "Same date of birth."}
    done = graph.invoke(Command(resume=answer), config)
    assert (done["risk_level"], done["decision"], done["reviewer"]) == ("high", "reject", "human")


def test_the_graph_chooses_its_models_only_through_get_model():
    source = (PROJECT_ROOT / "utils" / "nodes.py").read_text()
    assert "init_chat_model" not in source
    assert source.count("get_model(") == 2


def test_a_missing_recording_stops_the_graph_by_name(model_env, tmp_path):
    model_env.setenv("MODEL_BACKEND", "replay")
    model_env.setenv("MODEL_RECORDINGS_DIR", str(tmp_path))
    from fsi_common.model import ReplayMissError

    graph = starter.build_agent(checkpointer=InMemorySaver())
    with pytest.raises(ReplayMissError, match="no recording"):
        graph.invoke({"customer_id": "CUST-001"}, {"configurable": {"thread_id": "t-miss"}})
