"""The texts the validators read: clauses of the policy set and units of the regulations."""

from __future__ import annotations

from assessment.texts import split_clauses


def test_load_texts_reads_every_clause_and_every_unit(texts):
    assert texts.clause_count() == 360
    assert texts.clause_count(in_force_only=True) == 302
    assert texts.unit_count("DORA") == 501
    assert texts.unit_count("AI-ACT") == 930
    assert texts.unit_count("SS1-23") == 154


def test_load_texts_knows_the_version_in_force(texts):
    assert texts.in_force("HMB-POL-ICT-001-v3.0") is True
    assert texts.in_force("HMB-POL-ICT-001-v2.1") is False


def test_split_clauses_reads_numbered_lines_under_their_heading():
    text = (
        "# T\n\nStatus: In force\n\n## 4. Roles\n\n4.1 The Board approves.\n\n4.2 The CIO owns.\n"
    )
    clauses = split_clauses(text)
    assert [(c.number, c.heading, c.text) for c in clauses] == [
        ("4.1", "Roles", "The Board approves."),
        ("4.2", "Roles", "The CIO owns."),
    ]


def test_split_clauses_of_a_text_without_clauses_is_empty():
    assert split_clauses("# Only a title\n") == []
