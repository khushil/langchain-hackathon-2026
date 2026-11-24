"""Tests for the envelope that carries bound tools through `--json-schema`."""

from __future__ import annotations

import pytest
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from fsi_common.model.envelope import (
    build_envelope_schema,
    normalise_tools,
    parse_envelope,
)
from fsi_common.model.errors import MalformedResponseError, ModelConfigError


class Obligation(BaseModel):
    """Something a firm must do under the document."""

    requirement: str = Field(description="What the firm must do")
    paragraph: str = Field(description="The paragraph number")
    deadline: str | None = Field(description="The deadline as written, or null")
    evidence: str = Field(description="A word-for-word quote")


class SectionSummary(BaseModel):
    """A summary of one section of the document."""

    number: str
    title: str
    summary: str
    obligations: list[Obligation]


@tool
def get_document(document_id: str) -> dict:
    """A document in the library, as a JSON object with its sections."""
    return {"document_id": document_id}


def test_normalise_tools_accepts_tools_models_and_dicts() -> None:
    raw = {
        "type": "function",
        "function": {"name": "ping", "description": "Ping.", "parameters": {"type": "object"}},
    }
    specs = normalise_tools([get_document, SectionSummary, raw])
    assert [spec.name for spec in specs] == ["get_document", "SectionSummary", "ping"]
    assert specs[0].parameters["properties"]["document_id"]["type"] == "string"
    assert specs[1].description == "A summary of one section of the document."


def test_normalise_tools_refuses_duplicate_names() -> None:
    with pytest.raises(ModelConfigError, match="bound twice: get_document"):
        normalise_tools([get_document, get_document])


def test_envelope_has_content_and_one_branch_per_tool() -> None:
    specs = normalise_tools([get_document, SectionSummary])
    schema = build_envelope_schema(specs, tool_choice=None)
    assert schema["required"] == ["content", "tool_calls"]
    assert schema["additionalProperties"] is False
    branches = schema["properties"]["tool_calls"]["items"]["anyOf"]
    assert [b["properties"]["name"]["const"] for b in branches] == [
        "get_document",
        "SectionSummary",
    ]
    assert branches[1]["properties"]["args"]["required"] == [
        "number",
        "title",
        "summary",
        "obligations",
    ]
    assert "minItems" not in schema["properties"]["tool_calls"]


@pytest.mark.parametrize("choice", ["any", "required"])
def test_forced_choice_requires_at_least_one_call(choice: str) -> None:
    schema = build_envelope_schema(normalise_tools([get_document]), tool_choice=choice)
    assert schema["properties"]["tool_calls"]["minItems"] == 1


def test_named_choice_keeps_only_that_tool() -> None:
    specs = normalise_tools([get_document, SectionSummary])
    for choice in ("SectionSummary", {"type": "function", "function": {"name": "SectionSummary"}}):
        schema = build_envelope_schema(specs, tool_choice=choice)
        branches = schema["properties"]["tool_calls"]["items"]["anyOf"]
        assert [b["properties"]["name"]["const"] for b in branches] == ["SectionSummary"]
        assert schema["properties"]["tool_calls"]["minItems"] == 1


def test_named_choice_must_name_a_bound_tool() -> None:
    with pytest.raises(ModelConfigError, match="names no bound tool: missing"):
        build_envelope_schema(normalise_tools([get_document]), tool_choice="missing")


def test_none_choice_forbids_calls() -> None:
    schema = build_envelope_schema(normalise_tools([get_document]), tool_choice="none")
    assert schema["properties"]["tool_calls"]["maxItems"] == 0


def test_auto_choice_is_the_default() -> None:
    specs = normalise_tools([get_document])
    assert build_envelope_schema(specs, tool_choice="auto") == build_envelope_schema(
        specs, tool_choice=None
    )


def test_defs_are_hoisted_and_refs_rewritten() -> None:
    raw = {
        "name": "tree",
        "description": "A tree.",
        "parameters": {
            "type": "object",
            "properties": {"root": {"$ref": "#/$defs/Node"}},
            "$defs": {
                "Node": {
                    "type": "object",
                    "properties": {"kids": {"type": "array", "items": {"$ref": "#/$defs/Node"}}},
                }
            },
        },
    }
    schema = build_envelope_schema(normalise_tools([raw]), tool_choice=None)
    assert "tree__Node" in schema["$defs"]
    node = schema["$defs"]["tree__Node"]
    assert node["properties"]["kids"]["items"] == {"$ref": "#/$defs/tree__Node"}
    args = schema["properties"]["tool_calls"]["items"]["anyOf"][0]["properties"]["args"]
    assert "$defs" not in args
    assert args["properties"]["root"] == {"$ref": "#/$defs/tree__Node"}


def test_parse_envelope_returns_content_and_calls() -> None:
    specs = normalise_tools([get_document])
    parsed = parse_envelope(
        {
            "content": "Loading.",
            "tool_calls": [{"name": "get_document", "args": {"document_id": "X"}}],
        },
        specs,
    )
    assert parsed.content == "Loading."
    assert parsed.tool_calls == [("get_document", {"document_id": "X"})]


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (None, "no structured output"),
        ("text", "not a JSON object"),
        ({"tool_calls": []}, "content is missing or not a string"),
        ({"content": "", "tool_calls": "x"}, "tool_calls is not a list"),
        ({"content": "", "tool_calls": [{"name": "nope", "args": {}}]}, "unbound tool 'nope'"),
        ({"content": "", "tool_calls": [{"name": "get_document", "args": []}]}, "args of"),
    ],
)
def test_parse_envelope_refuses_malformed_payloads(payload: object, reason: str) -> None:
    with pytest.raises(MalformedResponseError, match=reason):
        parse_envelope(payload, normalise_tools([get_document]))
