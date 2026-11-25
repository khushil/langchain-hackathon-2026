"""The register's starting rule on the real texts: counts, and every seed applicable."""

from __future__ import annotations

from assessment.profile import load_profile
from assessment.provisions import load_seeds, match_seed
from assessment.register import build_register


def test_register_accounts_for_every_unit_and_states_its_population(texts):
    register = build_register(texts, load_profile("harbour-mutual-bank"))
    for key in ("DORA", "AI-ACT", "SS1-23"):
        population = register.population(key)
        assert population.units == texts.unit_count(key)
        assert population.obligations + population.not_obligations == population.units
        assert population.applicable <= population.obligations


def test_register_makes_every_seed_an_applicable_obligation(texts):
    register = build_register(texts, load_profile("harbour-mutual-bank"))
    unplaced = []
    for seed in load_seeds():
        targets = match_seed(seed, register)
        if not targets or not all(t.applies for t in targets):
            unplaced.append(seed.seed_id)
    assert unplaced == []


def test_register_populations_are_the_contracts_counts(texts):
    register = build_register(texts, load_profile("harbour-mutual-bank"))
    counts = {
        p.regulation: (p.units, p.obligations, p.applicable, p.not_applicable, p.undetermined)
        for p in register.populations
    }
    assert counts == {
        "DORA": (501, 219, 101, 117, 1),
        "AI-ACT": (930, 422, 21, 400, 1),
        "SS1-23": (154, 97, 97, 0, 0),
    }
