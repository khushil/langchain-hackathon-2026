"""The agents import with no model call, and a run refuses tracing with no key."""

import os
import subprocess
import sys
from pathlib import Path

TOPIC = Path(__file__).resolve().parent.parent
REPO = TOPIC.parent
CHECK = (
    "import sys, agent, agents; "
    "assert 'fsi_common.model' not in sys.modules, 'the adapter was imported'; "
    "assert agents.kyc_agent is agent.agent; "
    "assert agents.AGENTS['kyc_agent'] is agent.agent; "
    "assert agents.AGENTS['kyc_onboarding'] is agents.kyc_onboarding; "
    "assert agents.kyc_onboarding.name == 'kyc-onboarding'; "
    "print('imported')"
)
RUN = (
    "import agent; "
    "from langgraph.checkpoint.memory import InMemorySaver; "
    "graph = agent.build_agent(checkpointer=InMemorySaver()); "
    "graph.invoke({'customer_id': 'CUST-001'}, {'configurable': {'thread_id': 't'}})"
)


def _run(code, **env_changes):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LANGSMITH_", "LANGCHAIN_", "MODEL_"))
    }
    env |= {
        "PYTHONPATH": f"{REPO / 'fsi_common'}{os.pathsep}{TOPIC}",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    env |= env_changes
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=TOPIC,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_agents_import_on_replay_without_a_model_call():
    result = _run(CHECK, MODEL_BACKEND="replay", LANGSMITH_TRACING="false")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "imported"


def test_the_starters_graph_refuses_tracing_with_an_empty_key_when_it_runs():
    result = _run(RUN, MODEL_BACKEND="replay", LANGSMITH_TRACING="true", LANGSMITH_API_KEY="")
    assert result.returncode != 0
    assert "TracingKeyMissingError" in result.stderr


def test_the_starters_graph_stops_by_name_on_a_missing_recording(tmp_path):
    result = _run(
        RUN,
        MODEL_BACKEND="replay",
        LANGSMITH_TRACING="false",
        MODEL_RECORDINGS_DIR=str(tmp_path),
    )
    assert result.returncode != 0
    assert "ReplayMissError" in result.stderr


def test_the_graphs_are_registered_for_the_platform():
    import json

    registered = json.loads((TOPIC / "langgraph.json").read_text(encoding="utf-8"))["graphs"]
    assert registered == {
        "kyc_agent": "./agent.py:agent",
        "kyc_onboarding": "./workflow/graph.py:graph",
    }
