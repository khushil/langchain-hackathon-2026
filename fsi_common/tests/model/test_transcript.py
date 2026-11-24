"""Tests for turning a LangChain message history into the headless call's prompt."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from fsi_common.model.envelope import ToolSpec
from fsi_common.model.errors import ModelConfigError
from fsi_common.model.transcript import canonical_messages, render_prompt, render_system


def test_system_messages_are_lifted_out_and_joined() -> None:
    system, turns = canonical_messages(
        [SystemMessage("First."), HumanMessage("Hello"), SystemMessage("Second.")]
    )
    assert system == "First.\n\nSecond."
    assert turns == [{"role": "user", "content": "Hello"}]


def test_one_human_message_is_sent_as_plain_text() -> None:
    _, turns = canonical_messages([HumanMessage("Summarise section 7.")])
    assert render_prompt(turns) == "Summarise section 7."


def test_full_history_keeps_roles_calls_and_results() -> None:
    history = [
        HumanMessage("Summarise PS26-4"),
        AIMessage(
            content="Loading it.",
            tool_calls=[{"name": "get_document", "args": {"document_id": "PS26-4"}, "id": "c1"}],
        ),
        ToolMessage('{"title": "PS26-4"}', tool_call_id="c1", name="get_document"),
    ]
    _, turns = canonical_messages(history)
    assert turns[1] == {
        "role": "assistant",
        "content": "Loading it.",
        "tool_calls": [{"id": "c1", "name": "get_document", "args": {"document_id": "PS26-4"}}],
    }
    assert turns[2] == {
        "role": "tool",
        "content": '{"title": "PS26-4"}',
        "tool_call_id": "c1",
        "name": "get_document",
    }
    prompt = render_prompt(turns)
    assert prompt.index('<message role="user">') < prompt.index('<message role="assistant">')
    assert '<tool_call id="c1" name="get_document">{"document_id": "PS26-4"}</tool_call>' in prompt
    assert '<message role="tool" tool_call_id="c1" name="get_document">' in prompt
    assert prompt.rstrip().endswith("Write the assistant's next message.")


def test_text_blocks_are_joined_and_message_ids_ignored() -> None:
    first = HumanMessage(content=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
    second = HumanMessage(content="ab", id="different-id")
    assert canonical_messages([first])[1] == canonical_messages([second])[1]


def test_non_text_content_is_refused() -> None:
    image = HumanMessage(content=[{"type": "image", "url": "https://example.com/a.png"}])
    with pytest.raises(ModelConfigError, match="only text content"):
        canonical_messages([image])


def test_empty_history_is_refused() -> None:
    with pytest.raises(ModelConfigError, match="no message to answer"):
        canonical_messages([SystemMessage("Only a system prompt.")])


def test_system_prompt_lists_tools_only_when_bound() -> None:
    bare = render_system("Be brief.", [])
    assert bare.startswith("Be brief.")
    assert "tool_calls" not in bare
    spec = ToolSpec(name="get_document", description="Look up a document.", parameters={})
    with_tools = render_system("Be brief.", [spec])
    assert with_tools.startswith("Be brief.")
    assert "- get_document: Look up a document." in with_tools
    assert "tool_calls" in with_tools
    assert "No such tool available" in with_tools
