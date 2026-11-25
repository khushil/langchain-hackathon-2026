"""Tests of the seed register: each seeded case is well formed and its policy evidence is real."""

import re
from collections import Counter

from policy_support import hmb_policies, read_seeds, split_evidence

from context.text import contains_word_for_word

STATES = ("covered", "partly covered", "not covered", "in conflict")
REGULATIONS = {"DORA": "DORA", "AI Act": "AIA", "SS1/23": "SS123"}
_ARTICLE = r"Article \d+(\(\d+\))?(, (first|second|third) subparagraph)?(, point \([a-z]+\))?"
PROVISION = {
    "DORA": re.compile(rf"^{_ARTICLE}(\([ivx]+\))?$"),
    "AI Act": re.compile(rf"^({_ARTICLE}|Annex III, point \d\([a-z]\))$"),
    "SS1/23": re.compile(r"^(Principle \d\.\d(\([a-z]\))?(\([ivx]+\))?|paragraph \d\.\d)$"),
}
CHANGE_LOG_ENTRY = re.compile(r"^\d{1,2} [A-Z][a-z]+ \d{4}: \S")


def test_the_change_log_opens_with_the_date_the_seeds_were_written():
    comments, _ = read_seeds()
    assert "Change log" in comments
    entries = comments[comments.index("Change log") + 1 :]
    assert entries and all(CHANGE_LOG_ENTRY.match(entry) for entry in entries)
    assert entries[0].startswith("25 November 2026: ")


def test_every_seed_has_an_id_a_regulation_a_provision_and_a_state():
    _, rows = read_seeds()
    assert rows
    ids = [row["seed_id"] for row in rows]
    assert len(ids) == len(set(ids))
    for row in rows:
        assert row["regulation"] in REGULATIONS, row["seed_id"]
        assert re.fullmatch(rf"{REGULATIONS[row['regulation']]}-\d{{2}}", row["seed_id"])
        assert PROVISION[row["regulation"]].match(row["provision"]), row["seed_id"]
        assert row["provision_quote"].strip(), row["seed_id"]
        assert row["binds"].strip(), row["seed_id"]
        assert row["state"] in STATES, row["seed_id"]
        assert len(row["why"].split()) >= 8, row["seed_id"]


def test_seed_ids_run_in_order_within_each_regulation():
    _, rows = read_seeds()
    for regulation, prefix in REGULATIONS.items():
        ids = [row["seed_id"] for row in rows if row["regulation"] == regulation]
        assert ids == [f"{prefix}-{n:02d}" for n in range(1, len(ids) + 1)], regulation


def test_the_register_holds_every_state_and_each_regulation_a_covered_and_a_gap():
    _, rows = read_seeds()
    assert {row["state"] for row in rows} == set(STATES)
    for regulation in REGULATIONS:
        states = Counter(row["state"] for row in rows if row["regulation"] == regulation)
        assert states["covered"] >= 1, regulation
        assert sum(states.values()) - states["covered"] >= 1, regulation


def test_every_quoted_clause_is_word_for_word_in_the_document_it_cites():
    policies = hmb_policies()
    checked = 0
    for row in read_seeds()[1]:
        documents = split_evidence(row["documents"])
        clauses = split_evidence(row["clauses"])
        quotes = split_evidence(row["clause_quotes"])
        assert len(documents) == len(clauses) == len(quotes), row["seed_id"]
        for document, clause, quote in zip(documents, clauses, quotes, strict=True):
            assert document in policies, f"{row['seed_id']} cites {document}"
            text = policies[document].clauses.get(clause)
            assert text is not None, f"{row['seed_id']} cites {document} clause {clause}"
            assert contains_word_for_word(quote, text), f"{row['seed_id']} {document} {clause}"
            checked += 1
    assert checked >= len(read_seeds()[1])


def test_every_clause_offered_as_coverage_is_in_a_document_in_force():
    policies = hmb_policies()
    for row in read_seeds()[1]:
        if row["state"] == "not covered":
            continue
        documents = split_evidence(row["documents"])
        assert documents, row["seed_id"]
        superseded = [d for d in documents if policies[d].control["Status"] != "In force"]
        assert not superseded, f"{row['seed_id']} offers {superseded} as coverage"


def test_a_seed_not_covered_says_why_any_clause_it_cites_falls_short():
    for row in read_seeds()[1]:
        if row["state"] == "not covered" and split_evidence(row["clauses"]):
            assert re.search(r"superseded|only|does not|no clause|silent", row["why"]), row[
                "seed_id"
            ]


def test_a_conflict_cites_the_clause_that_conflicts():
    for row in read_seeds()[1]:
        if row["state"] == "in conflict":
            assert split_evidence(row["clauses"]), row["seed_id"]
            assert "conflict" in row["why"].lower() or "contradict" in row["why"].lower()
