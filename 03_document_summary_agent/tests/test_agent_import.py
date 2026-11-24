"""Tests that the agents import with no model call and refuse tracing with no key."""

import os
import subprocess
import sys
from pathlib import Path

TOPIC = Path(__file__).resolve().parent.parent
REPO = TOPIC.parent
CHECK = (
    "import sys, agent, agents; "
    "from utils.models import DeferredChatModel; "
    "assert 'fsi_common.model' not in sys.modules, 'the adapter was imported'; "
    "spec = agents.AGENTS['section-summariser']; "
    "assert isinstance(spec['model'], DeferredChatModel) and spec['model'].role == 'section'; "
    "assert agents.document_summary_agent is agent.agent; "
    "print('imported')"
)


def _run(**env_changes):
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
        [sys.executable, "-c", CHECK],
        cwd=TOPIC,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_agents_import_on_replay_without_a_model_call():
    result = _run(MODEL_BACKEND="replay", LANGSMITH_TRACING="false")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "imported"


def test_agents_refuse_tracing_with_an_empty_key():
    result = _run(MODEL_BACKEND="replay", LANGSMITH_TRACING="true", LANGSMITH_API_KEY="")
    assert result.returncode != 0
    assert "TracingKeyMissingError" in result.stderr
