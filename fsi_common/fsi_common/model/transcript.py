"""Turn a LangChain message history into the system prompt and prompt of one headless call."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

from fsi_common.model.envelope import ToolSpec
from fsi_common.model.errors import ModelConfigError

_ROLES = {"human": "user", "ai": "assistant", "tool": "tool"}

_TOOL_NOTE = """\
Your reply is one JSON object, given through the StructuredOutput tool, with `content` (your \
text, which may be empty) and `tool_calls` (a list, which may be empty). The tools listed below \
are not functions you can call in this session: calling one directly fails with "No such tool \
available". To use one, add {"name": <tool name>, "args": <arguments>} to `tool_calls` in your \
StructuredOutput answer; the caller runs each listed call and sends its result back in a later \
message. Several calls in one answer run in parallel. The tools you may list:"""

EMPTY_SYSTEM_PROMPT = "You are a careful assistant."

_HISTORY_NOTE = (
    "The conversation so far is below, oldest first. Each tool result answers the tool call "
    "with the same id."
)


def _text(content: Any) -> str:
    """Join a message's text, refusing any block that is not text."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        else:
            kind = block.get("type") if isinstance(block, dict) else type(block).__name__
            raise ModelConfigError(
                f"The headless model takes only text content; a message carried a {kind!r} block."
            )
    return "".join(parts)


def canonical_messages(messages: Sequence[BaseMessage]) -> tuple[str, list[dict[str, Any]]]:
    """Split a history into its system text and its turns, in a canonical, hashable form.

    Args:
        messages: The LangChain messages of one model call.

    Returns:
        The system messages' text joined by blank lines, and one dict per other message with
        its role, text, and its tool calls or the call it answers. Message ids are left out.

    Raises:
        ModelConfigError: If a message carries non-text content or no turn is left to answer.
    """
    system_parts: list[str] = []
    turns: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            system_parts.append(_text(message.content))
            continue
        turn: dict[str, Any] = {
            "role": _ROLES.get(message.type, message.type),
            "content": _text(message.content),
        }
        if isinstance(message, AIMessage) and message.tool_calls:
            turn["tool_calls"] = [
                {"id": call.get("id"), "name": call["name"], "args": call["args"]}
                for call in message.tool_calls
            ]
        if isinstance(message, ToolMessage):
            turn["tool_call_id"] = message.tool_call_id
            turn["name"] = message.name
        turns.append(turn)
    if not turns:
        raise ModelConfigError("The history has no message to answer, only a system prompt.")
    return "\n\n".join(part for part in system_parts if part), turns


def render_prompt(turns: Sequence[dict[str, Any]]) -> str:
    """Render the turns as the call's prompt: plain text for one user turn, else a transcript.

    Args:
        turns: The canonical turns from `canonical_messages`.

    Returns:
        The text sent to the headless call on standard input.
    """
    if len(turns) == 1 and turns[0]["role"] == "user":
        return turns[0]["content"]
    lines = [_HISTORY_NOTE, "", "<conversation>"]
    for turn in turns:
        if turn["role"] == "tool":
            lines.append(
                f'<message role="tool" tool_call_id="{turn["tool_call_id"]}" name="{turn["name"]}">'
            )
        else:
            lines.append(f'<message role="{turn["role"]}">')
        if turn["content"]:
            lines.append(turn["content"])
        for call in turn.get("tool_calls", []):
            args = json.dumps(call["args"], ensure_ascii=False)
            lines.append(f'<tool_call id="{call["id"]}" name="{call["name"]}">{args}</tool_call>')
        lines.append("</message>")
    lines += ["</conversation>", "", "Write the assistant's next message."]
    return "\n".join(lines)


def render_system(system_text: str, specs: Sequence[ToolSpec]) -> str:
    """Render the system prompt: the caller's own text, then how to call any bound tools.

    Args:
        system_text: The caller's system messages, joined.
        specs: The bound tools; with none, the caller's text is sent unchanged.

    Returns:
        The text passed with `--system-prompt`; never empty, so Claude Code's own default
        prompt is never used in its place.
    """
    if not specs:
        return system_text or EMPTY_SYSTEM_PROMPT
    listing = "\n".join(f"- {spec.name}: {spec.description}" for spec in specs)
    head = f"{system_text}\n\n" if system_text else ""
    return f"{head}{_TOOL_NOTE}\n{listing}"
