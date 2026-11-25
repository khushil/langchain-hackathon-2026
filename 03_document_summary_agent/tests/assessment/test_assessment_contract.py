"""The assessment contract: provisions, seed matching, derived states, records and the bundle."""

from __future__ import annotations

import pytest
from assessment.bundle import read_bundle, write_bundle
from assessment.fake import FAKE_SEEDS, build_fake_bundle, plant_invalid_bundle
from assessment.provisions import (
    ProvisionLabelError,
    derive_state,
    load_seeds,
    resolve_provision,
)
from assessment.records import Assessment
from assessment.validate import BundleInvalidError, require_valid, validate_bundle

from fsi_common.records import Decision, Person, SignOff


def test_resolve_provision_every_seed_names_a_real_place(texts):
    seeds = load_seeds()
    assert len(seeds) == 55
    for seed in seeds:
        ref = resolve_provision(seed.regulation, seed.provision)
        assert texts.has_place(ref.regulation, ref.anchor), (seed.seed_id, ref)


@pytest.mark.parametrize(
    ("regulation", "label", "anchor", "points"),
    [
        ("DORA", "Article 5(2)", "art:5/2", ()),
        ("DORA", "Article 30(2), point (b)", "art:30/2", ("b",)),
        ("DORA", "Article 30(3), point (e)(i)", "art:30/3", ("e", "i")),
        ("DORA", "Article 11(6), first subparagraph, point (a)", "art:11/6", ("a",)),
        ("AI Act", "Article 4", "art:4", ()),
        ("SS1/23", "Principle 1.3(c)(ii)", "prin:1.3/c", ("ii",)),
        ("SS1/23", "Principle 5.1", "subprinciple:5.1", ()),
        ("SS1/23", "paragraph 3.8", "para:3.8", ()),
    ],
)
def test_resolve_provision_forms(regulation, label, anchor, points):
    ref = resolve_provision(regulation, label)
    assert (ref.anchor, ref.points) == (anchor, points)


@pytest.mark.parametrize("label", ["", "Recital 7", "Article five", "Principle 9(z)(q)(r)(s)"])
def test_resolve_provision_refuses_what_it_cannot_place(label):
    with pytest.raises(ProvisionLabelError, match="cannot be placed"):
        resolve_provision("DORA" if "Principle" not in label else "SS1/23", label)


@pytest.mark.parametrize(
    ("states", "derived"),
    [
        (["covered", "covered"], "covered"),
        (["covered", "not covered"], "partly covered"),
        (["not covered", "not covered"], "not covered"),
        (["covered", "in conflict"], "in conflict"),
        (["partly covered"], "partly covered"),
    ],
)
def test_derive_state(states, derived):
    assert derive_state(states) == derived


def test_derive_state_refuses_an_empty_group():
    with pytest.raises(ValueError, match="no state"):
        derive_state([])


def test_fake_bundle_passes_the_validators(texts):
    bundle = build_fake_bundle(texts)
    report = validate_bundle(bundle, texts)
    assert report.faults == [], report.faults
    assert report.line.startswith("valid:")
    require_valid(bundle, texts)


def test_fake_bundle_covers_every_state_and_the_seeds_it_names(texts):
    bundle = build_fake_bundle(texts)
    states = {a.state for a in bundle.assessments}
    assert states == {"covered", "partly covered", "not covered", "in conflict"}
    matched = {m.seed_id for m in bundle.seed_matches}
    assert matched == set(FAKE_SEEDS)
    assert any(
        not o.applies for o in bundle.obligation_register.obligations if o.applies is not None
    )


@pytest.mark.parametrize(
    "fault",
    [
        "clause-quote-not-verbatim",
        "provision-quote-not-verbatim",
        "applicable-obligation-not-assessed",
        "clause-neither-mapped-nor-listed",
        "not-covered-without-second-look",
        "superseded-clause-covers",
        "graph-fact-object-quote",
        "derived-state-mismatch",
        "compliance-words",
        "gap-missing",
        "state-without-clause",
        "register-unit-unaccounted",
        "partial-scope",
        "inapplicable-obligation-assessed",
        "graph-fact-subject-quote",
        "points-incomplete",
        "evidence-missing",
        "judgement-missing",
        "seed-match-wrong",
    ],
)
def test_planted_invalid_bundle_fails_naming_its_fault(texts, fault):
    bundle = plant_invalid_bundle(build_fake_bundle(texts), fault)
    report = validate_bundle(bundle, texts)
    assert fault in {f.check for f in report.faults}, report.faults
    with pytest.raises(BundleInvalidError, match=fault):
        require_valid(bundle, texts)


def test_plant_invalid_bundle_refuses_an_unknown_fault(texts):
    with pytest.raises(KeyError, match="no planted fault"):
        plant_invalid_bundle(build_fake_bundle(texts), "nothing-like-this")


def test_assessment_id_recomputes_and_a_person_decides_on_it(texts):
    assessment = build_fake_bundle(texts).assessments[0]
    again = Assessment.model_validate(assessment.to_json())
    assert again.id == assessment.id and again.id.startswith("assessment:")
    decision = Decision.on(
        assessment,
        outcome="amend",
        amendment="Clause 4.1 covers the provision; the gap wording is withdrawn.",
        reason="Read both texts side by side.",
        reviewer=Person(name="Alex Morgan", role="Head of Compliance"),
        date="2026-11-25",
    )
    assert decision.subject_id == assessment.id


def test_gap_report_is_a_brief_a_person_signs(texts):
    bundle = build_fake_bundle(texts)
    report = bundle.gap_report
    cited = {fact_id for s in report.statements for fact_id in s.cites}
    assert cited <= {f.id for f in bundle.facts}
    signoff = SignOff.build(
        brief_id=report.id,
        brief_digest=report.content_digest,
        reviewer=Person(name="Alex Morgan", role="Head of Compliance"),
        date="2026-11-25",
        outcome="signed",
        assumptions=[],
    )
    assert signoff.brief_id == report.id


def test_bundle_round_trips_through_its_files(texts, tmp_path):
    bundle = build_fake_bundle(texts)
    folder = write_bundle(bundle, tmp_path)
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [
            "bundle.json",
            "register.json",
            "candidates.jsonl",
            "judgements.jsonl",
            "assessments.jsonl",
            "facts.jsonl",
            "clause_map.jsonl",
            "seed_matches.jsonl",
            "gap_report.json",
        ]
    )
    again = read_bundle(folder)
    assert again == bundle
    assert validate_bundle(again, texts).faults == []


def test_every_check_has_a_planted_fault(texts):
    from assessment.fake import _PLANTS
    from assessment.validate import CHECKS

    assert sorted(_PLANTS) == sorted(CHECKS)
