"""Candidates found by code: terms, defined terms, cross references, the graph, a second look."""

from __future__ import annotations

from collections import Counter

import pytest
from assessment.candidates import (
    KEPT_LIMIT,
    find_candidates,
    stems_of,
    without_candidates,
)
from assessment.graph import build_graph
from assessment.profile import load_profile
from assessment.provisions import load_seeds, match_seed
from assessment.register import build_register


@pytest.fixture(scope="module")
def register(texts):
    return build_register(texts, load_profile("harbour-mutual-bank"))


@pytest.fixture(scope="module")
def graph(texts):
    return build_graph(texts)


@pytest.fixture(scope="module")
def first(texts, register, graph):
    return find_candidates(register, texts, graph, second_look=False)


def _applicable(register):
    return [o for o in register.obligations if o.applies is True]


def test_stems_of_drops_stop_words_and_folds_endings():
    assert stems_of("The financial entities shall maintain registers of arrangements") == {
        "financial",
        "entity",
        "maintain",
        "register",
        "arrange",
    }


def test_candidates_are_found_for_applicable_obligations_only(register, first):
    applicable = {o.obligation_id for o in _applicable(register)}
    assert {c.obligation_id for c in first} <= applicable
    assert len({c.obligation_id for c in first}) >= 200


def test_a_kept_candidate_sits_in_a_document_in_force_and_a_superseded_one_is_dropped(texts, first):
    for c in first:
        if c.kept:
            assert texts.in_force(c.clause.document), c
        if not texts.in_force(c.clause.document):
            assert c.kept is False
            assert c.reason.startswith("superseded version")
    assert any(not texts.in_force(c.clause.document) for c in first)


def test_every_candidate_names_a_real_clause_and_what_matched(texts, first):
    for c in first:
        assert texts.clause_text(c.clause.document, c.clause.clause) is not None
        assert c.found_by and c.matched and all(m.strip() for m in c.matched)


def test_kept_candidates_per_obligation_are_bounded_and_the_overflow_is_logged(first):
    kept = Counter(c.obligation_id for c in first if c.kept)
    assert max(kept.values()) <= KEPT_LIMIT
    overflow = [c for c in first if not c.kept and c.reason.startswith("ranked below")]
    assert overflow, "at least one obligation has more candidates than the limit"


def test_no_clause_is_listed_twice_for_one_obligation(first):
    keys = Counter((c.obligation_id, c.clause.document, c.clause.clause) for c in first)
    assert [k for k, n in keys.items() if n > 1] == []


def test_the_clauses_the_seeds_cite_are_kept_as_candidates_for_their_obligations(
    texts, register, first
):
    kept = {(c.obligation_id, c.clause.document, c.clause.clause) for c in first if c.kept}
    pairs = []
    for seed in load_seeds():
        for obligation in match_seed(seed, register):
            for document, clause in seed.clauses:
                if texts.in_force(document):
                    pairs.append((obligation.obligation_id, document, clause))
    found = sum(p in kept for p in pairs)
    assert len(pairs) == 70
    assert found >= 58, f"{found} of {len(pairs)}"


def test_a_clause_that_names_an_article_is_a_cross_reference_candidate(texts, register, first):
    found = [
        c
        for c in first
        if "cross_reference" in c.found_by and c.kept and c.obligation_id.startswith("AI-ACT art:5")
    ]
    assert [(c.clause.document, c.clause.clause) for c in found] == [("HMB-STD-AI-014-v1.0", "8.1")]


def test_a_clause_next_to_a_kept_clause_in_the_graph_is_found_by_the_graph(first):
    assert any("graph" in c.found_by and c.kept for c in first)


def test_a_defined_term_in_both_texts_is_found_by_the_defined_term(first):
    assert any("defined_term" in c.found_by and c.kept for c in first)


def test_without_candidates_lists_the_applicable_obligations_with_no_kept_clause(register, first):
    none = without_candidates(register, first)
    kept = {c.obligation_id for c in first if c.kept}
    assert {o.obligation_id for o in none} == {
        o.obligation_id for o in _applicable(register)
    } - kept


def test_the_second_look_widens_the_search_and_marks_what_it_finds(texts, register, graph, first):
    base = _applicable(register)[0]
    poor = base.model_copy(
        update={
            "obligation_id": "DORA art:9999/1",
            "provision_words": "Exit plans shall exist.",
            "parents": [],
        }
    )
    sub = register.model_copy(update={"obligations": [poor]})
    before = find_candidates(sub, texts, graph, second_look=False)
    after = find_candidates(sub, texts, graph, second_look=True)
    assert [c for c in before if c.kept] == []
    widened = [c for c in after if c.kept]
    assert widened and all("second_look" in c.found_by for c in widened)


def test_an_obligation_that_shares_nothing_has_no_candidate_on_either_look(texts, register, graph):
    base = _applicable(register)[0]
    odd = base.model_copy(
        update={
            "obligation_id": "DORA art:9998/1",
            "provision_words": "Quokkas shall wobble in unison at dawn.",
            "parents": [],
        }
    )
    sub = register.model_copy(update={"obligations": [odd]})
    for look in (False, True):
        assert [c for c in find_candidates(sub, texts, graph, second_look=look) if c.kept] == []


def _strip_channels(monkeypatch):
    import dataclasses

    from assessment import candidates as module

    real = module._first_look

    def stripped(corpus, obligation, *, second_look):
        hits, surface = real(corpus, obligation, second_look=second_look)
        return [dataclasses.replace(h, channels=()) for h in hits], surface

    monkeypatch.setattr(module, "_first_look", stripped)


@pytest.mark.parametrize(
    ("second_look", "bar"), [(False, "3 terms of weight 10"), (True, "2 terms of weight 6")]
)
def test_the_below_the_bar_reason_quotes_the_bar_that_applied(
    register, texts, graph, monkeypatch, second_look, bar
):
    _strip_channels(monkeypatch)
    one = register.model_copy(update={"obligations": [_applicable(register)[0]]})
    found = find_candidates(one, texts, graph, second_look=second_look)
    reasons = {c.reason for c in found if c.reason.startswith("below the bar")}
    assert reasons, "a hit without a channel is logged as below the bar"
    assert all(f"where {bar} are needed" in r for r in reasons), reasons
