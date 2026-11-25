"""The document graph the engine finds by code: five relations, a quote at both ends of each."""

from __future__ import annotations

from collections import Counter

import pytest
from assessment.graph import (
    GraphEdge,
    build_graph,
    defined_terms,
    edges_of,
    resolve_reference,
)

ICT3 = "HMB-POL-ICT-001-v3.0"
ICT21 = "HMB-POL-ICT-001-v2.1"


@pytest.fixture(scope="module")
def graph(texts):
    return build_graph(texts)


def _edges(texts, graph, relation):
    return [e for e in edges_of(texts, graph) if e.relation == relation]


def test_graph_has_every_relation_and_unique_ids(graph):
    kinds = Counter(f.kind for f in graph)
    assert set(kinds) == {"implements", "refers_to", "supersedes", "defines", "delegates"}
    assert len({f.id for f in graph}) == len(graph)


def test_every_graph_fact_has_a_word_for_word_quote_at_both_ends(texts, graph):
    bad = []
    for f in graph:
        a = f.attributes
        if not texts.quote_at(f.subject.source_id, f.subject.anchor, f.quote):
            bad.append(("subject", f.id))
        if not texts.quote_at(a["object_source_id"], a["object_anchor"], a["object_quote"]):
            bad.append(("object", f.id))
    assert bad == []


def test_supersedes_links_version_3_to_version_2_1_and_no_other_version(texts, graph):
    found = _edges(texts, graph, "supersedes")
    assert [(e.source_document, e.object_document) for e in found] == [(ICT3, ICT21)]


def test_delegates_follow_the_framework_by_document_level(texts, graph):
    found = {(e.object_document, e.source_anchor) for e in _edges(texts, graph, "delegates")}
    assert found == {
        ("HMB-STD-ICT-011-v1.3", "clause:5.2"),
        ("HMB-STD-AI-014-v1.0", "clause:5.2"),
        ("HMB-PRO-ICT-021-v1.2", "clause:5.3"),
    }


def test_implements_names_the_section_a_standard_implements(texts, graph):
    found = {
        (e.source_document, e.source_anchor, e.object_document, e.object_anchor)
        for e in _edges(texts, graph, "implements")
        if e.object_document and e.object_document.startswith("HMB")
    }
    assert ("HMB-STD-ICT-011-v1.3", "clause:1.1", ICT3, "clause:11.1") in found
    assert ("HMB-PRO-ICT-021-v1.2", "clause:1.1", ICT3, "clause:8.1") in found
    assert ("HMB-STD-AI-014-v1.0", "clause:1.1", "HMB-POL-MRM-004-v2.0", "clause:6.1") in found


def test_a_reference_to_a_document_outside_the_corpus_makes_no_edge(texts, graph):
    # HMB-STD-ICT-019 is named by the policy but is not in the corpus; no edge may point at it.
    assert resolve_reference(texts, "HMB-STD-ICT-019", from_document=ICT3) is None
    assert all("ICT-019" not in str(e.object_document) for e in edges_of(texts, graph))


def test_a_reference_to_a_reference_with_two_versions_takes_the_one_in_force(texts):
    assert resolve_reference(texts, "HMB-POL-ICT-001", from_document="HMB-STD-ICT-011-v1.3") == ICT3


def test_a_clause_citing_an_article_of_a_regulation_links_to_that_article(texts, graph):
    found = [
        e
        for e in _edges(texts, graph, "refers_to")
        if e.object_regulation == "DORA" and e.object_anchor.startswith("art:20")
    ]
    assert [(e.source_document, e.source_anchor) for e in found] == [
        ("HMB-PRO-ICT-021-v1.2", "clause:8.2")
    ]


def test_a_definition_links_to_the_first_use_in_each_other_document(texts, graph):
    found = [
        e
        for e in _edges(texts, graph, "defines")
        if e.term == "Management Body" and e.object_document == ICT3
    ]
    assert len(found) == 1
    assert (found[0].source_document, found[0].source_anchor) == (
        "HMB-FRM-GOV-000-v2.0",
        "clause:4.2",
    )
    assert found[0].object_anchor == "clause:4.1"


def test_defined_terms_reads_quoted_terms_that_a_clause_defines():
    clauses = {
        "D": [
            _C("4.2", '"Management Body" means the board.'),
            _C("4.3", "Terms with capital letters mean what the framework says."),
        ]
    }
    assert defined_terms(clauses) == {"Management Body": ("D", "4.2")}


def test_a_term_defined_in_a_document_in_force_is_preferred_to_an_earlier_superseded_one():
    clauses = {
        "OLD": [_C("3.2", '"ICT risk" means the old words.')],
        "NEW": [_C("3.2", '"ICT risk" means the new words.')],
    }
    assert defined_terms(clauses) == {"ICT risk": ("OLD", "3.2")}
    assert defined_terms(clauses, in_force={"NEW"}) == {"ICT risk": ("NEW", "3.2")}
    assert defined_terms(clauses, in_force={"OLD", "NEW"}) == {"ICT risk": ("OLD", "3.2")}


def test_graph_edge_is_a_frozen_record():
    edge = GraphEdge(
        relation="refers_to",
        source_document="D",
        source_anchor="clause:1.1",
        object_document="E",
        object_regulation=None,
        object_anchor="control:reference",
        term=None,
    )
    with pytest.raises(AttributeError):
        edge.relation = "defines"  # type: ignore[misc]


class _C:
    def __init__(self, number, text):
        self.number, self.text, self.heading = number, text, "h"
