"""A notebook step that needs LangSmith runs only when the reader has set the key and tracing on."""

import pytest

from utils.langsmith_key import NEEDS_KEY, langsmith_ready


def test_the_sentence_names_the_settings_the_reader_needs_and_is_one_sentence():
    assert "LANGSMITH_API_KEY" in NEEDS_KEY and "LANGSMITH_TRACING=true" in NEEDS_KEY
    assert NEEDS_KEY.count(". ") == 0 and NEEDS_KEY.endswith(".")
    assert "\n" not in NEEDS_KEY


@pytest.mark.parametrize(
    ("env", "ready"),
    [
        ({"LANGSMITH_API_KEY": "k", "LANGSMITH_TRACING": "true"}, True),
        ({"LANGSMITH_API_KEY": "k", "LANGSMITH_TRACING": "True"}, True),
        ({"LANGCHAIN_API_KEY": "k", "LANGCHAIN_TRACING_V2": "true"}, True),
        ({"LANGSMITH_API_KEY": "k"}, False),
        ({"LANGSMITH_API_KEY": "k", "LANGSMITH_TRACING": "false"}, False),
        ({"LANGSMITH_TRACING": "true"}, False),
        ({"LANGSMITH_API_KEY": "  ", "LANGSMITH_TRACING": "true"}, False),
        ({}, False),
    ],
)
def test_ready_needs_both_a_key_and_tracing_switched_on(env, ready):
    assert langsmith_ready(env) is ready


def test_the_environment_is_read_when_none_is_given(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "k")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    assert langsmith_ready() is True
    monkeypatch.delenv("LANGSMITH_API_KEY")
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    assert langsmith_ready() is False
