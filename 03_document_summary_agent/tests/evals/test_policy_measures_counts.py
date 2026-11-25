"""The four policy measures, each counted by regulation over the population it states."""

import json

import pytest
from assessment.provisions import resolve_provision

from evals.policy_dataset import SeedCase
from evals.policy_measures import (
    MatchRow,
    MeasureInputError,
    count_of,
    measure_seeds,
    read_seed_matches,
    report_lines,
)

ICT = "HMB-POL-ICT-001-v3.0"
GOV = "HMB-FRM-GOV-000-v2.0"
PROVISIONS = {"DORA": "Article 5(2)", "AI-ACT": "Article 26(11)", "SS1-23": "Principle 1.1(a)"}


def seed(seed_id, regulation="DORA", state="covered", clauses=((ICT, "4.1"),)):
    return SeedCase(
        seed_id=seed_id,
        regulation=regulation,
        provision=PROVISIONS[regulation],
        provision_quote="words",
        state=state,
        clauses=tuple(clauses),
        clause_quotes=tuple("quote" for _ in clauses),
    )


def match(
    seed_case,
    found=None,
    cited=None,
    *,
    regulation=None,
    seeded_state=None,
    target=None,
    points=None,
):
    place = resolve_provision(seed_case.regulation, seed_case.provision)
    return MatchRow(
        seed_id=seed_case.seed_id,
        regulation=regulation or seed_case.regulation,
        target=target or place.anchor,
        points=place.points if points is None else tuple(points),
        found_state=found or seed_case.state,
        seeded_state=seeded_state or seed_case.state,
        cited=tuple(seed_case.clauses if cited is None else cited),
        seeded=seed_case.clauses,
    )


def counted(report, measure, scope):
    found = count_of(report, measure, scope)
    return found.numerator, found.denominator


def test_seeded_gaps_found_counts_every_state_other_than_covered_over_the_seeded_gaps():
    gaps = [
        seed("D1", state="not covered", clauses=()),
        seed("D2", state="partly covered"),
        seed("D3", state="in conflict"),
        seed("D4", state="covered"),
    ]
    matches = [
        match(gaps[0], "partly covered", ()),
        match(gaps[1], "covered"),
        match(gaps[2], "in conflict"),
        match(gaps[3]),
    ]
    report = measure_seeds(gaps, matches)
    assert counted(report, "seeded_gaps_found", "DORA") == (2, 3)
    assert counted(report, "seeded_gaps_found", "all") == (2, 3)


def test_same_state_counts_the_seeds_whose_found_state_is_the_seeded_state():
    seeds = [
        seed("D1", state="partly covered"),
        seed("D2", state="covered"),
        seed("D3", state="not covered", clauses=()),
    ]
    matches = [match(seeds[0], "not covered", ()), match(seeds[1]), match(seeds[2])]
    assert counted(measure_seeds(seeds, matches), "same_state", "DORA") == (2, 3)


def test_false_gaps_counts_covered_seeds_found_as_anything_else():
    seeds = [seed("D1"), seed("D2"), seed("D3", state="partly covered")]
    matches = [match(seeds[0], "partly covered"), match(seeds[1]), match(seeds[2], "covered")]
    report = measure_seeds(seeds, matches)
    assert counted(report, "false_gaps", "DORA") == (1, 2)


def test_a_seed_found_covered_that_the_labels_hold_as_a_gap_is_not_a_false_gap():
    seeds = [seed("D1", state="partly covered")]
    report = measure_seeds(seeds, [match(seeds[0], "covered")])
    assert counted(report, "false_gaps", "DORA") == (0, 0)


def test_wrong_citations_counts_cited_clauses_with_none_among_the_seeded_ones():
    seeds = [seed("D1", clauses=[(ICT, "4.1"), (GOV, "5.2")]), seed("D2"), seed("D3")]
    matches = [
        match(seeds[0], cited=[(GOV, "5.2")]),
        match(seeds[1], cited=[(ICT, "9.9")]),
        match(seeds[2], cited=[(ICT, "4.1"), (ICT, "9.9")]),
    ]
    assert counted(measure_seeds(seeds, matches), "wrong_citations", "DORA") == (1, 3)


def test_the_same_clause_number_in_another_document_is_a_wrong_citation():
    seeds = [seed("D1", clauses=[(ICT, "4.1")])]
    report = measure_seeds(seeds, [match(seeds[0], cited=[(GOV, "4.1")])])
    assert counted(report, "wrong_citations", "DORA") == (1, 1)


def test_a_found_state_of_not_covered_leaves_the_citation_population():
    seeds = [seed("D1", state="not covered", clauses=[(ICT, "4.1")])]
    report = measure_seeds(seeds, [match(seeds[0], cited=[])])
    assert counted(report, "wrong_citations", "DORA") == (0, 0)


def test_a_state_other_than_not_covered_that_cites_nothing_is_a_wrong_citation():
    seeds = [seed("D1")]
    report = measure_seeds(seeds, [match(seeds[0], "partly covered", [])])
    assert counted(report, "wrong_citations", "DORA") == (1, 1)


def test_a_citation_on_a_seed_that_names_no_clause_is_listed_and_never_scored():
    seeds = [seed("D1", state="not covered", clauses=())]
    report = measure_seeds(seeds, [match(seeds[0], "partly covered", [(ICT, "4.1")])])
    assert counted(report, "wrong_citations", "DORA") == (0, 0)
    assert report.uncompared == ("D1",)


def test_each_regulation_is_counted_on_its_own_and_all_adds_them_up():
    seeds = [
        seed("D1", "DORA", "partly covered"),
        seed("A1", "AI-ACT", "not covered", ()),
        seed("S1", "SS1-23", "in conflict"),
        seed("S2", "SS1-23", "partly covered"),
    ]
    matches = [match(seeds[0]), match(seeds[1], "covered", ()), match(seeds[2]), match(seeds[3])]
    report = measure_seeds(seeds, matches)
    assert counted(report, "seeded_gaps_found", "DORA") == (1, 1)
    assert counted(report, "seeded_gaps_found", "AI-ACT") == (0, 1)
    assert counted(report, "seeded_gaps_found", "SS1-23") == (2, 2)
    assert counted(report, "seeded_gaps_found", "all") == (3, 4)


def test_a_seed_with_no_match_stays_in_the_denominators_and_is_listed():
    seeds = [seed("D1", state="partly covered"), seed("D2", state="partly covered")]
    report = measure_seeds(seeds, [match(seeds[0])])
    assert counted(report, "seeded_gaps_found", "DORA") == (1, 2)
    assert counted(report, "same_state", "DORA") == (1, 2)
    assert report.unmatched == ("D2",)
    assert report.total_seeds == 2


def test_a_count_names_the_seeds_it_counted_and_the_seeds_of_its_population():
    seeds = [seed("D1", state="partly covered"), seed("D2", state="partly covered")]
    report = measure_seeds(seeds, [match(seeds[0]), match(seeds[1], "not covered", ())])
    found = count_of(report, "seeded_gaps_found", "DORA")
    assert found.counted == ("D1", "D2") and found.population == ("D1", "D2")
    same = count_of(report, "same_state", "DORA")
    assert same.counted == ("D1",)


def test_no_seeds_gives_every_measure_a_zero_population():
    report = measure_seeds([], [])
    for measure in ("seeded_gaps_found", "same_state", "false_gaps", "wrong_citations"):
        assert counted(report, measure, "all") == (0, 0)
    assert report.unmatched == ()


def test_lines_are_the_ones_the_run_prints_for_each_regulation_and_for_all():
    seeds = [seed("D1", state="partly covered"), seed("A1", "AI-ACT"), seed("S1", "SS1-23")]
    lines = report_lines(measure_seeds(seeds, [match(s) for s in seeds]))
    assert "seeded_gaps_found [DORA]: 1 of 1 seeded gaps" in lines
    assert "seeded_gaps_found [AI Act]: none in scope" in lines
    assert "seeded_gaps_found [all]: 1 of 1 seeded gaps" in lines
    assert "false_gaps [AI Act]: 0 of 1 seeds the labels hold as covered" in lines
    assert "false_gaps [SS1/23]: 0 of 1 seeds the labels hold as covered" in lines
    assert (
        "wrong_citations [DORA]: 0 of 1 seeds that name clauses "
        "and were found as anything but not covered"
    ) in lines
    assert "same_state [all]: 3 of 3 seeds" in lines
    assert len(lines) == 16


def test_every_line_sits_with_its_measure_in_regulation_order():
    lines = report_lines(measure_seeds([], []))
    scopes = [line.split("[")[1].split("]")[0] for line in lines]
    assert scopes == ["DORA", "AI Act", "SS1/23", "all"] * 4
    assert [line.split(" ")[0] for line in lines[::4]] == [
        "seeded_gaps_found",
        "same_state",
        "false_gaps",
        "wrong_citations",
    ]


def test_a_match_for_a_seed_the_file_does_not_hold_is_refused():
    seeds = [seed("D1")]
    stray = match(seed("D9"))
    with pytest.raises(MeasureInputError, match="D9"):
        measure_seeds(seeds, [match(seeds[0]), stray])


def test_two_matches_for_one_seed_are_refused():
    seeds = [seed("D1")]
    with pytest.raises(MeasureInputError, match="D1.*twice"):
        measure_seeds(seeds, [match(seeds[0]), match(seeds[0])])


def test_a_match_whose_seeded_state_differs_from_the_file_is_refused():
    seeds = [seed("D1", state="not covered", clauses=())]
    with pytest.raises(MeasureInputError, match="D1.*seeded state"):
        measure_seeds(seeds, [match(seeds[0], "not covered", (), seeded_state="covered")])


def test_a_match_whose_regulation_differs_from_the_file_is_refused():
    seeds = [seed("D1")]
    with pytest.raises(MeasureInputError, match="D1.*regulation"):
        measure_seeds(seeds, [match(seeds[0], regulation="SS1-23")])


def test_a_match_whose_seeded_clauses_differ_from_the_file_is_refused():
    seeds = [seed("D1")]
    stale = MatchRow(
        "D1", "DORA", "art:5/2", (), "covered", "covered", ((ICT, "4.1"),), ((ICT, "7.7"),)
    )
    with pytest.raises(MeasureInputError, match="D1.*seeded clauses"):
        measure_seeds(seeds, [stale])


def good_row(**change):
    row = {
        "seed_id": "DORA-01",
        "regulation": "DORA",
        "target": "art:5/2",
        "points": [],
        "obligation_ids": ["DORA art:5/2"],
        "found_state": "covered",
        "seeded_state": "covered",
        "cited_clauses": [{"document": ICT, "clause": "4.1"}],
        "seeded_clauses": [{"document": ICT, "clause": "4.1"}],
    }
    row.update(change)
    return row


def write_rows(tmp_path, *rows):
    path = tmp_path / "seed_matches.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_seed_matches_are_read_from_the_bundles_own_file_layout(tmp_path):
    (found,) = read_seed_matches(write_rows(tmp_path, good_row()))
    assert found == MatchRow(
        "DORA-01", "DORA", "art:5/2", (), "covered", "covered", ((ICT, "4.1"),), ((ICT, "4.1"),)
    )


def test_an_empty_seed_matches_file_reads_as_no_matches(tmp_path):
    assert read_seed_matches(write_rows(tmp_path)) == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"found_state": "approved"}, "found_state"),
        ({"seeded_state": None}, "seeded_state"),
        ({"cited_clauses": "4.1"}, "cited_clauses"),
        ({"cited_clauses": [{"document": ICT}]}, "cited_clauses"),
        ({"seed_id": ""}, "seed_id"),
        ({"target": ""}, "target"),
        ({"points": "b"}, "points"),
        ({"points": [1]}, "points"),
    ],
)
def test_a_malformed_seed_match_is_refused_naming_the_file_and_line(tmp_path, change, message):
    path = write_rows(tmp_path, good_row(), good_row(**{"seed_id": "DORA-02", **change}))
    with pytest.raises(MeasureInputError, match=rf"seed_matches.jsonl.*line 2.*{message}"):
        read_seed_matches(path)


def test_a_line_that_is_not_json_is_refused_naming_its_line(tmp_path):
    path = tmp_path / "seed_matches.jsonl"
    path.write_text(json.dumps(good_row()) + "\n{not json\n", encoding="utf-8")
    with pytest.raises(MeasureInputError, match="line 2"):
        read_seed_matches(path)


def test_a_missing_seed_matches_file_is_refused_naming_it(tmp_path):
    with pytest.raises(MeasureInputError, match="absent.jsonl"):
        read_seed_matches(tmp_path / "absent.jsonl")


@pytest.mark.parametrize("key", ["seeded_clauses", "target", "points"])
def test_a_key_missing_from_a_row_is_refused(tmp_path, key):
    row = good_row()
    del row[key]
    with pytest.raises(MeasureInputError, match=key):
        read_seed_matches(write_rows(tmp_path, row))


def test_a_match_placed_on_another_obligation_is_refused_naming_the_seed():
    seeds = [seed("D1")]
    with pytest.raises(MeasureInputError, match=r"D1.*art:5/3.*art:5/2"):
        measure_seeds(seeds, [match(seeds[0], target="art:5/3")])


def test_a_match_placed_on_the_right_unit_and_the_wrong_point_is_refused_naming_the_seed():
    one = SeedCase(
        "D1", "DORA", "Article 30(2), point (b)", "words", "covered", ((ICT, "4.1"),), ("q",)
    )
    assert match(one).points == ("b",)
    with pytest.raises(MeasureInputError, match=r"D1.*point"):
        measure_seeds([one], [match(one, points=("f",))])


def test_a_seed_whose_provision_cannot_be_placed_is_refused_naming_it():
    odd = SeedCase("D1", "DORA", "Recital 4", "words", "covered", ((ICT, "4.1"),), ("q",))
    row = MatchRow(
        "D1", "DORA", "art:4", (), "covered", "covered", ((ICT, "4.1"),), ((ICT, "4.1"),)
    )
    with pytest.raises(MeasureInputError, match=r"D1.*Recital 4"):
        measure_seeds([odd], [row])


def test_the_placement_of_a_match_is_checked_even_when_nothing_else_is_wrong():
    seeds = [seed("S1", "SS1-23", "partly covered"), seed("A1", "AI-ACT")]
    clean = [match(s) for s in seeds]
    assert measure_seeds(seeds, clean).unmatched == ()
    with pytest.raises(MeasureInputError, match="A1"):
        measure_seeds(seeds, [clean[0], match(seeds[1], target="art:26/12")])
