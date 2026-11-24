"""The brief writer is told to write in words: names for firms and providers, none named."""

from __future__ import annotations

from workflow.briefing import BRIEF_INSTRUCTIONS


def _rules() -> list[str]:
    return [line[2:] for line in BRIEF_INSTRUCTIONS.splitlines() if line.startswith("- ")]


def test_the_writer_is_told_to_name_the_firm_and_providers_never_by_their_codes():
    rule = next(r for r in _rules() if "name" in r.lower() and "provider" in r.lower())
    assert "firm" in rule and "never" in rule
    assert "identifier" in rule or "code" in rule


def test_the_writer_is_told_to_say_none_named_for_a_missing_value_and_never_null():
    rule = next(r for r in _rules() if "none named" in r)
    assert "null" in rule and "never" in rule


def test_the_writer_is_told_a_fact_line_is_for_citing_not_for_copying():
    assert any("anchor" in r and "cit" in r for r in _rules())
