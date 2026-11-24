"""The fake chat model and replay error topic 03's tests import by name.

They live here, under a name no other member uses, and not in ``conftest.py``: with every
member's tests collected in one run, ``from conftest import ...`` can reach another member's
``conftest`` first.
"""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
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
