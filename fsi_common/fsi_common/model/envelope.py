"""The JSON Schema envelope that carries bound tools and tool calls through `--json-schema`."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.utils.function_calling import convert_to_openai_tool

from fsi_common.model.errors import MalformedResponseError, ModelConfigError

_FORCING_CHOICES = {"any", "required"}
_FREE_CHOICES = {None, "auto"}


@dataclass(frozen=True)
class ToolSpec:
    """One bound tool: its name, description and JSON Schema for its arguments."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ParsedEnvelope:
    """The model's reply read out of the envelope: its text and its tool calls in order."""

    content: str
    tool_calls: list[tuple[str, dict[str, Any]]]


def normalise_tools(tools: Sequence[Any]) -> list[ToolSpec]:
    """Convert LangChain tools, Pydantic models and tool dicts into tool specs.

    Args:
        tools: Anything `convert_to_openai_tool` accepts, or a dict with `name` and `parameters`.

    Returns:
        One spec per tool, in the order given.

    Raises:
        ModelConfigError: If two tools share a name.
    """
    specs: list[ToolSpec] = []
    for item in tools:
        if isinstance(item, dict) and "name" in item and "parameters" in item:
            function = item
        else:
            function = convert_to_openai_tool(item)["function"]
        parameters = copy.deepcopy(
            function.get("parameters") or {"type": "object", "properties": {}}
        )
        specs.append(ToolSpec(function["name"], function.get("description", ""), parameters))
    names = [spec.name for spec in specs]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ModelConfigError(f"A tool name is bound twice: {', '.join(duplicates)}.")
    return specs


def _choice_name(tool_choice: Any) -> str | None:
    """Return the tool a choice names, or None when it names none."""
    if isinstance(tool_choice, dict):
        function = tool_choice.get("function") or {}
        return function.get("name") or tool_choice.get("name")
    if isinstance(tool_choice, str) and tool_choice not in _FORCING_CHOICES | {"auto", "none"}:
        return tool_choice
    return None


def _rewrite_refs(node: Any, prefix: str) -> Any:
    """Point every local `$ref` in a schema at its hoisted, prefixed definition."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and value.startswith("#/$defs/"):
                out[key] = f"#/$defs/{prefix}__{value.removeprefix('#/$defs/')}"
            else:
                out[key] = _rewrite_refs(value, prefix)
        return out
    if isinstance(node, list):
        return [_rewrite_refs(item, prefix) for item in node]
    return node


def build_envelope_schema(specs: Sequence[ToolSpec], *, tool_choice: Any) -> dict[str, Any]:
    """Build the envelope schema: the reply's text and a list of calls to the bound tools.

    Args:
        specs: The bound tools.
        tool_choice: None or "auto" lets the model choose; "any" or "required" forces at least
            one call; a tool's name, or a dict naming one, forces a call to that tool; "none"
            forbids calls.

    Returns:
        A JSON Schema whose `tool_calls` items are one branch per allowed tool.

    Raises:
        ModelConfigError: If the choice names a tool that is not bound.
    """
    named = _choice_name(tool_choice)
    allowed = list(specs)
    if named is not None:
        allowed = [spec for spec in specs if spec.name == named]
        if not allowed:
            raise ModelConfigError(f"The tool choice names no bound tool: {named}.")
    defs: dict[str, Any] = {}
    branches = []
    for spec in allowed:
        args = copy.deepcopy(spec.parameters)
        for def_name, definition in (args.pop("$defs", None) or {}).items():
            defs[f"{spec.name}__{def_name}"] = _rewrite_refs(definition, spec.name)
        branches.append(
            {
                "type": "object",
                "description": spec.description,
                "properties": {
                    "name": {"const": spec.name},
                    "args": _rewrite_refs(args, spec.name),
                },
                "required": ["name", "args"],
                "additionalProperties": False,
            }
        )
    calls: dict[str, Any] = {"type": "array", "items": {"anyOf": branches}}
    if named is not None or tool_choice in _FORCING_CHOICES:
        calls["minItems"] = 1
    elif tool_choice == "none":
        calls["maxItems"] = 0
    elif tool_choice not in _FREE_CHOICES:
        raise ModelConfigError(f"The tool choice {tool_choice!r} is not one the adapter knows.")
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Text of the reply; may be empty."},
            "tool_calls": calls,
        },
        "required": ["content", "tool_calls"],
        "additionalProperties": False,
    }
    if defs:
        schema["$defs"] = defs
    return schema


def parse_envelope(payload: Any, specs: Sequence[ToolSpec]) -> ParsedEnvelope:
    """Read the reply's text and tool calls out of a structured output.

    Args:
        payload: The `structured_output` of the headless call's result.
        specs: The bound tools; a call to any other name is refused.

    Returns:
        The parsed reply.

    Raises:
        MalformedResponseError: If the payload is absent or not in the envelope's shape.
    """
    if payload is None:
        raise MalformedResponseError("The call returned no structured output for its envelope.")
    if not isinstance(payload, dict):
        raise MalformedResponseError("The structured output is not a JSON object.")
    content = payload.get("content")
    if not isinstance(content, str):
        raise MalformedResponseError("The envelope's content is missing or not a string.")
    raw_calls = payload.get("tool_calls", [])
    if not isinstance(raw_calls, list):
        raise MalformedResponseError("The envelope's tool_calls is not a list.")
    known = {spec.name for spec in specs}
    calls: list[tuple[str, dict[str, Any]]] = []
    for position, call in enumerate(raw_calls):
        name = call.get("name") if isinstance(call, dict) else None
        if name not in known:
            raise MalformedResponseError(f"Call {position} names an unbound tool {name!r}.")
        args = call.get("args")
        if not isinstance(args, dict):
            raise MalformedResponseError(f"The args of call {position} ({name}) are not an object.")
        calls.append((name, args))
    return ParsedEnvelope(content=content, tool_calls=calls)
