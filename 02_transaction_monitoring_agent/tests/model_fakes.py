"""The fake chat model and replay error topic 02's tests import by name.

They live here, under a name no other member uses, and not in ``conftest.py``: with every
member's tests collected in one run, ``from conftest import ...`` can reach another member's
``conftest`` first.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class FakeChatModel(BaseChatModel):
    """A chat model that answers every call with one fixed reply and records what it was given."""

    reply: str = "fake reply"
    calls: list[Any] = []
    bound: Any = None
    structured: Any = None

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.reply))])

    def bind_tools(self, tools, **kwargs):
        self.bound = (tools, kwargs)
        return self

    def with_structured_output(self, schema, **kwargs):
        self.structured = (schema, kwargs)
        return self


class FakeReplayMissError(Exception):
    """Stands in for the adapter's ReplayMissError."""


# The assessor's script, for tests of the starter's agent and the workflow that runs it.

TRANSACTION_ID = re.compile(r"TX-\d+")


@dataclass(frozen=True)
class Assessment:
    """What the scripted assessor records for one transaction, or ``None`` to record nothing."""

    risk_score: int
    confidence: float
    decision: str
    reason: str
    record_as: str | None = None
    """When set, the assessor records under this transaction id instead of the one it was sent."""


def assessment_for_score(score: int, *, confidence: float = 0.9, reason: str = "") -> Assessment:
    """Return an assessment whose decision follows the starter's rule: block from 70 up."""
    decision = "block" if score >= 70 else "approve"
    return Assessment(score, confidence, decision, reason or f"Scripted reason for score {score}.")


def current_transaction(messages: list) -> tuple[str, list]:
    """Return the id of the transaction the last request is about, and the messages after it."""
    humans = [
        index
        for index, message in enumerate(messages)
        if isinstance(message, HumanMessage) and TRANSACTION_ID.search(str(message.content))
    ]
    last = humans[-1]
    return TRANSACTION_ID.search(str(messages[last].content)).group(0), messages[last + 1 :]


class ScriptedAssessor(BaseChatModel):
    """Plays the starter's agent's model: looks up the transaction and profile, then records one
    assessment from ``script`` and replies in a sentence. A transaction missing from the script, or
    scripted as ``None``, is looked up and then answered without a recorded assessment."""

    script: dict[str, Any] = {}
    calls: list[Any] = []
    owner: Any = None

    @property
    def _llm_type(self) -> str:
        return "scripted-assessor"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        tx, after = current_transaction(messages)
        if self.owner is not None and not [m for m in after if isinstance(m, ToolMessage)]:
            self.owner.visit(tx)
        names = [m.name for m in after if isinstance(m, ToolMessage)]
        assessment = self.script.get(tx)
        if not names:
            calls = [
                {"name": "get_transaction", "args": {"transaction_id": tx}, "id": f"c-{tx}-1"},
                {"name": "get_customer_profile", "args": {}, "id": f"c-{tx}-2"},
            ]
            message = AIMessage(content="", tool_calls=calls)
        elif "record_decision" in names or assessment is None:
            message = AIMessage(content=f"Looked at {tx}.")
        else:
            args = {
                "transaction_id": assessment.record_as or tx,
                "risk_score": assessment.risk_score,
                "confidence": assessment.confidence,
                "decision": assessment.decision,
                "reason": assessment.reason,
            }
            message = AIMessage(
                content="",
                tool_calls=[{"name": "record_decision", "args": args, "id": f"c-{tx}-3"}],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])


def envelope_runner_reply(script: dict[str, Any]):
    """Return a responder for the adapter's fake runner that plays ``ScriptedAssessor``'s part.

    The responder reads the transcript the adapter sends on standard input and answers with the
    envelope the real adapter would parse, so a recorded run and its replay can be tested
    without a model.
    """
    from fsi_common.model.headless import RawRun

    def stream(structured: dict[str, Any]) -> str:
        init = {
            "type": "system",
            "subtype": "init",
            "cwd": "/tmp/fsi-model-test",
            "model": "claude-sonnet-5-5",
            "tools": ["StructuredOutput"],
            "mcp_servers": [],
            "plugins": [],
            "slash_commands": [],
            "skills": [],
            "agents": [],
            "apiKeySource": "none",
            "claude_code_version": "2.1.302",
        }
        done = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "",
            "num_turns": 1,
            "duration_ms": 1,
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "structured_output": structured,
        }
        return "\n".join(json.dumps(event) for event in (init, done)) + "\n"

    def respond(call) -> Any:
        prompt = call.stdin
        found = TRANSACTION_ID.findall(prompt)
        tx = found[-1]
        tail = (
            prompt[prompt.rindex(f"New transaction: {tx}") :] if "New transaction" in prompt else ""
        )
        if 'role="tool"' not in tail:
            payload = {
                "content": "",
                "tool_calls": [
                    {"name": "get_transaction", "args": {"transaction_id": tx}},
                    {"name": "get_customer_profile", "args": {}},
                ],
            }
        elif 'name="record_decision"' in tail or script.get(tx) is None:
            payload = {"content": f"Looked at {tx}.", "tool_calls": []}
        else:
            a = script[tx]
            args = {
                "transaction_id": tx,
                "risk_score": a.risk_score,
                "confidence": a.confidence,
                "decision": a.decision,
                "reason": a.reason,
            }
            payload = {"content": "", "tool_calls": [{"name": "record_decision", "args": args}]}
        return RawRun(0, stream(payload), "")

    return respond


@dataclass
class ScriptedCall:
    """One call the scripted runner received, as the adapter's runner interface passes it."""

    argv: list[str]
    stdin: str


class ScriptedRunner:
    """Stands in for the headless process: answers each call the way ``ScriptedAssessor`` would."""

    def __init__(self, script: dict[str, Any]) -> None:
        self.respond = envelope_runner_reply(script)
        self.calls: list[ScriptedCall] = []

    def run(self, argv, *, stdin, env, cwd, timeout):
        """Answer one call synchronously."""
        self.calls.append(ScriptedCall(list(argv), stdin))
        return self.respond(self.calls[-1])

    async def arun(self, argv, *, stdin, env, cwd, timeout):
        """Answer one call on the event loop."""
        return self.run(argv, stdin=stdin, env=env, cwd=cwd, timeout=timeout)
