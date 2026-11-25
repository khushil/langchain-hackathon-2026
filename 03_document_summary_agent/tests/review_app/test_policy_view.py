"""What the policy pages show, read from the fake bundle: counts close and the words hold."""

from __future__ import annotations

import pytest
from assessment.bundle import read_bundle
from policy_pages_support import (
    CORPUS,
    DANA,
    TODAY,
    left_out_bundle,
    with_a_loose_statement,
    write_fake,
)

from fsi_common.records import Decision, Person
from review_app import policy_view as view
from review_app import review_route

ERIK = Person(name="Erik Lund", role="Head of Technology Risk")


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    bundle, root = write_fake(tmp_path_factory.mktemp("view"))
    return view.PolicyData(read_bundle(root / CORPUS), view.read_documents(CORPUS))


def decide_all(data, outcome="accept"):
    out = {}
    for assessment in data.bundle.assessments:
        if assessment.state != "covered":
            out[assessment.id] = review_route.decide_assessment(
                assessment, outcome=outcome, reason="Read.", amendment=None, person=DANA, on=TODAY
            )
    return out


def test_the_documents_in_force_are_six_of_seven_and_the_superseded_one_is_not_a_column(data):
    assert len(data.documents) == 7
    assert [d.in_force for d in data.documents].count(True) == 6
    picture = view.picture_view(data)
    assert len(picture.documents) == 6
    assert all(d.in_force for d in picture.documents)
    assert "HMB-POL-ICT-001-v2.1" not in {d.doc_id for d in picture.documents}


def test_the_picture_holds_one_row_for_each_obligation_that_applies_and_none_other(data):
    picture = view.picture_view(data)
    counts = {block.key: sum(len(g.rows) for g in block.groups) for block in picture.regulations}
    assert counts == {"DORA": 101, "AI-ACT": 21, "SS1-23": 97}
    ids = [r.obligation_id for b in picture.regulations for g in b.groups for r in g.rows]
    applying = {o.obligation_id for o in data.bundle.obligation_register.obligations if o.applies}
    assert len(ids) == len(set(ids)) == 219 and set(ids) == applying


def test_the_leading_regulation_comes_first_and_each_line_states_its_population(data):
    picture = view.picture_view(data)
    assert [b.key for b in picture.regulations] == ["DORA", "AI-ACT", "SS1-23"]
    assert [b.line for b in picture.regulations] == [
        "101 of 219 DORA obligations apply",
        "21 of 422 AI Act obligations apply",
        "97 of 97 SS1/23 obligations apply",
    ]


def test_a_row_shows_the_assessments_state_and_marks_only_the_documents_it_quotes(data):
    picture = view.picture_view(data)
    rows = {r.obligation_id: r for b in picture.regulations for g in b.groups for r in g.rows}
    for assessment in data.bundle.assessments:
        row = rows[assessment.obligation_id]
        assert row.state == assessment.state
        cited = {q.clause.document for q in assessment.clause_quotes}
        marked = {c.document for c in row.cells if c.cited}
        assert marked == {d for d in cited if d in {c.document for c in row.cells}}
    unassessed = [r for r in rows.values() if r.state is None]
    assert len(unassessed) == 219 - len(data.bundle.assessments)
    assert all(not c.cited and c.kind == "blank" for r in unassessed for c in r.cells)


def test_rows_are_grouped_under_the_chapter_and_article_they_sit_in(data):
    picture = view.picture_view(data)
    dora = next(b for b in picture.regulations if b.key == "DORA")
    labels = [g.label for g in dora.groups]
    assert labels[0] == "Chapter I, Article 4" and "Chapter II, Article 5" in labels
    ss = next(b for b in picture.regulations if b.key == "SS1-23")
    assert any("Principle 5.1" in g.label for g in ss.groups)
    assert view.parent_label("subprinciple:5.1") == "Principle 5.1"


def test_the_picture_sentence_counts_the_assessed_states_and_names_the_firm(data):
    answer = view.picture_answer(data, {})
    assert answer.sentence == (
        "13 of 219 obligations that apply to Harbour Mutual Bank are assessed against the "
        "documents in force: 3 covered, 2 partly covered, 7 not covered and 1 in conflict."
    )
    assert [t.value for t in answer.tiles] == ["219 of 738", "10", "0 of 10"]
    decided = view.picture_answer(data, decide_all(data))
    assert decided.tiles[2].value == "10 of 10"


def test_the_register_lists_every_obligation_with_its_reason_and_two_are_left_to_a_person(data):
    table = view.register_table(
        data, sort=None, descending=False, href_for=lambda **_: "", export_href="x.csv"
    )
    assert len(table.rows) == 738
    assert all(row["reason"].text for row in table.rows)
    assert sum(r["applies"].text == "Applies" for r in table.rows) == 219
    assert sum(r["applies"].text == "Does not apply" for r in table.rows) == 517
    questions = view.open_questions(data)
    assert len(questions) == 2 == sum(r["applies"].status == "needs_person" for r in table.rows)
    assert {q.label for q in questions} == {"Article 26(1)", "Article 50(2)"}
    linked = [r for r in table.rows if r["obligation"].href]
    assert len(linked) == 219


def test_the_register_sorts_by_a_column_and_keeps_every_row(data):
    table = view.register_table(
        data, sort="obligation", descending=True, href_for=lambda **_: "", export_href="x"
    )
    assert len(table.rows) == 738
    ids = [r["obligation"].sort_value for r in table.rows]
    assert ids == sorted(ids, key=view_natural, reverse=True)


def view_natural(text):
    from fsi_common.app.pages import natural_key

    return natural_key(text)


def test_one_assessment_page_gives_the_provision_the_points_the_clauses_and_the_checks(data):
    page = view.assessment_page(data, "DORA art:30/2")
    assert page.assessment.state == "partly covered"
    assert [p.label for p in page.points] == list("abcdefghi")
    assert any(s.marked for s in page.provision)
    assert page.clauses and all(c.found and c.in_force for c in page.clauses)
    assert page.checks and page.candidates
    assert page.previous is None or page.previous.startswith(view.PREFIX)
    assert page.following.endswith("/obligations/DORA/art:30/3") or "/DORA/" in page.following


def test_an_obligation_that_does_not_apply_or_does_not_exist_has_no_page(data):
    not_apply = next(o for o in data.bundle.obligation_register.obligations if o.applies is False)
    assert view.assessment_page(data, not_apply.obligation_id) is None
    assert view.assessment_page(data, "DORA art:99999") is None


def test_an_obligation_that_applies_but_was_not_assessed_still_has_a_page_that_says_so(data):
    unassessed = next(o for o in data.applicable() if o.obligation_id not in data.assessments)
    page = view.assessment_page(data, unassessed.obligation_id)
    assert page.assessment is None and page.clauses == () and page.points == ()
    answer = view.assessment_answer(page, None)
    assert "has not been assessed against the documents in force" in answer.sentence


def test_a_decision_changes_the_tile_of_the_assessment_it_is_on(data):
    page = view.assessment_page(data, "DORA art:30/2")
    waiting = view.assessment_answer(page, None).tiles[2]
    assert (waiting.value, waiting.status) == ("Waiting", "needs_person")
    decision = Decision.on(
        page.assessment, outcome="accept", reason="Read.", reviewer=DANA, date=TODAY
    )
    assert view.assessment_answer(page, decision).tiles[2].value == "Decided"


def test_the_clauses_table_has_every_clause_in_force_and_names_the_reason_of_an_unmapped_one(data):
    table = view.clauses_table(
        data, sort=None, descending=False, href_for=lambda **_: "", export_href="x"
    )
    assert len(table.rows) == 302
    mapped = [r for r in table.rows if r["mapped"].status == "normal"]
    unmapped = [r for r in table.rows if r["mapped"].status == "needs_person"]
    assert len(mapped) + len(unmapped) == 302
    assert all(r["mapped"].text for r in unmapped)
    assert view.clauses_answer(data).tiles[1].value == f"{len(mapped)} of 302"


def test_the_graph_holds_one_edge_of_each_kind_with_both_ends_named_and_quoted(data):
    edges = view.graph_edges(data)
    assert sorted(e.relation for e in edges) == sorted(
        ["implements", "refers_to", "supersedes", "defines", "delegates"]
    )
    implements = next(e for e in edges if e.relation == "implements")
    assert implements.to_name == "DORA" and implements.to_place == "Article 6(1)"
    assert "Financial entities shall have" in implements.to_quote
    assert all(e.from_quote and e.to_quote and e.from_name and e.to_name for e in edges)
    assert "A document" not in {e.from_name for e in edges} | {e.to_name for e in edges}


def test_the_gap_report_lists_each_gap_with_its_assessment_and_the_decision_on_it(data):
    held = decide_all(data)
    statements = view.gap_statements(data, held)
    gaps = [a for a in data.bundle.assessments if a.state != "covered"]
    assert len(statements) == len(gaps) == 10
    assert all(s.decision is not None for s in statements)
    assert statements[0].label.startswith(("DORA", "AI Act", "SS1/23"))
    assert statements[0].heading in {"DORA", "AI Act", "SS1/23"}
    assert {s.assessment_id for s in statements} == {a.id for a in gaps}


def test_the_gap_report_can_be_signed_only_when_every_gap_is_decided_and_none_rejected(data):
    assert "10 gaps have no decision from you" in view.cannot_sign_because(data, {})
    partial = dict(list(decide_all(data).items())[:9])
    assert "1 gap has no decision from you" in view.cannot_sign_because(data, partial)
    assert view.cannot_sign_because(data, decide_all(data)) is None
    refused = view.cannot_sign_because(data, decide_all(data, "reject"))
    assert refused.startswith("You rejected 10 gaps")


def test_a_gap_report_is_not_signed_over_decisions_another_person_made(data):
    held = decide_all(data)
    assert view.cannot_sign_because(data, held, person=DANA) is None
    problem = view.cannot_sign_because(data, held, person=ERIK)
    assert problem == (
        f"Decisions on this gap report were made by {DANA.name}, {DANA.role}. Sign in as that "
        "person to sign it, or record your own decisions again."
    )
    own = {
        a.id: review_route.decide_assessment(
            a, outcome="accept", reason="Read.", amendment=None, person=ERIK, on=TODAY
        )
        for a in data.bundle.assessments
        if a.state != "covered"
    }
    mixed = {**own, next(iter(held)): next(iter(held.values()))}
    assert view.cannot_sign_because(data, mixed, person=ERIK) == problem
    assert view.cannot_sign_because(data, own, person=ERIK) is None
    assert "10 gaps have no decision from you" in view.cannot_sign_because(data, {}, person=ERIK)


def test_a_statement_that_rests_on_no_assessment_refuses_the_sign_off_and_is_named(data):
    held = decide_all(data)
    loose = view.PolicyData(with_a_loose_statement(data.bundle), data.documents)
    assert len(view.gap_statements(loose, held)) == 10
    unplaced = view.unplaced_statements(loose)
    assert [s.text for s in unplaced] == ["A gap nobody assessed."]
    problem = view.cannot_sign_because(loose, held, person=DANA)
    assert "A gap nobody assessed." in problem and "no assessment" in problem
    assert view.unplaced_statements(data) == ()
    assert view.cannot_sign_because(data, held, person=DANA) is None


def _largest_share(data, state, others):
    """Return a copy of the data whose assessments are given the states, in order."""
    assessed = [a for a in data.bundle.assessments if a.state != "covered"]
    states = [state] * others + ["not covered"] * (len(assessed) - others)
    changed = {a.id: a.model_copy(update={"state": s}) for a, s in zip(assessed, states)}
    every = [changed.get(a.id, a) for a in data.bundle.assessments]
    return view.PolicyData(data.bundle.model_copy(update={"assessments": every}), data.documents)


def test_the_proposal_sentence_names_the_state_with_the_most_gaps(data):
    partly = _largest_share(data, "partly covered", 8)
    assert view.proposal_sentence(partly) == (
        'Every finding is a proposal that a person decides. "Partly covered" is where the engine '
        "asks for a person most."
    )
    mostly = _largest_share(data, "partly covered", 2)
    assert view.proposal_sentence(mostly) == (
        'Every finding is a proposal that a person decides. "Not covered" is where the engine '
        "asks for a person most."
    )
    tied = _largest_share(data, "partly covered", 5)
    assert '"Partly covered" and "Not covered" are where' in view.proposal_sentence(tied)
    nothing = view.PolicyData(
        data.bundle.model_copy(
            update={
                "assessments": [
                    a.model_copy(update={"state": "covered"}) for a in data.bundle.assessments
                ]
            }
        ),
        data.documents,
    )
    assert view.proposal_sentence(nothing) == "Every finding is a proposal that a person decides."


def test_the_next_gap_without_the_persons_decision_follows_the_page_and_wraps_round(data):
    held = decide_all(data)
    gaps = [
        a
        for a in data.applicable()
        if data.assessments.get(a.obligation_id)
        and data.assessments[a.obligation_id].state != "covered"
    ]
    ids = [o.obligation_id for o in gaps]
    assert len(ids) == 10
    assert view.next_open_gap(data, {}, person=DANA) == view.href_obligation(data, ids[0])
    assert view.next_open_gap(data, {}, person=DANA, after=ids[0]) == view.href_obligation(
        data, ids[1]
    )
    assert view.next_open_gap(data, {}, person=DANA, after=ids[-1]) == view.href_obligation(
        data, ids[0]
    )
    assert view.next_open_gap(data, held, person=DANA) is None
    assert view.next_open_gap(data, held, person=ERIK) == view.href_obligation(data, ids[0])
    one_left = {k: v for k, v in held.items() if k != data.assessments[ids[3]].id}
    assert view.next_open_gap(data, one_left, person=DANA) == view.href_obligation(data, ids[3])
    assert view.next_open_gap(data, one_left, person=DANA, after=ids[3]) is None
    assert view.next_open_gap(
        data, one_left, person=DANA, after="DORA art:1/1"
    ) == view.href_obligation(data, ids[3])


def test_no_sentence_of_the_view_says_a_firm_complies_or_does_not(data):
    import re

    claim = re.compile(r"\bcompl(?:y|ies|iant|iance)\b", re.I)
    held = decide_all(data)
    page = view.assessment_page(data, "DORA art:8/7")
    words = [
        view.picture_answer(data, held).sentence,
        view.register_answer(data).sentence,
        view.clauses_answer(data).sentence,
        view.graph_answer(view.graph_edges(data), data).sentence,
        view.gap_report_answer(data, held, None).sentence,
        view.assessment_answer(page, None).sentence,
        *(s.text for s in view.gap_statements(data, held)),
    ]
    assert not [w for w in words if claim.search(w)]


def test_the_four_figures_count_the_seed_matches_of_the_bundle_with_their_populations(data):
    figures = {f.key: f for f in view.measure_figures(data)}
    matches = data.bundle.seed_matches
    gaps = [m for m in matches if m.seeded_state != "covered"]
    covered = [m for m in matches if m.seeded_state == "covered"]
    assert (figures["gaps_found"].found, figures["gaps_found"].of) == (
        sum(m.found_state != "covered" for m in gaps),
        len(gaps),
    )
    assert (figures["false_gaps"].found, figures["false_gaps"].of) == (
        sum(m.found_state != "covered" for m in covered),
        len(covered),
    )
    assert figures["same_state"].of == len(matches) == 8
    assert figures["same_state"].found == sum(m.found_state == m.seeded_state for m in matches)
    cited = [m for m in matches if m.seeded_clauses and m.found_state != "not covered"]
    assert figures["wrong_citations"].of == len(cited)
    wrong = [
        m
        for m in cited
        if not {(c.document, c.clause) for c in m.cited_clauses}
        & {(c.document, c.clause) for c in m.seeded_clauses}
    ]
    assert figures["wrong_citations"].found == len(wrong)
    assert [f.key for f in view.measure_figures(data)] == [
        "gaps_found",
        "false_gaps",
        "wrong_citations",
        "same_state",
    ]


def wrong_citations(matches) -> int:
    """Count, apart from the view, the findings whose cited clauses share none with the seeds'."""
    return sum(
        1
        for m in matches
        if m.seeded_clauses
        and m.found_state != "not covered"
        and not {(c.document, c.clause) for c in m.cited_clauses}
        & {(c.document, c.clause) for c in m.seeded_clauses}
    )


def test_a_citation_is_wrong_only_when_none_of_the_clauses_cited_was_seeded(data):
    bundle = data.bundle
    match = next(
        m for m in bundle.seed_matches if m.seeded_clauses and m.found_state != "not covered"
    )
    nowhere = match.seeded_clauses[0].model_copy(update={"clause": "99.99"})
    for cited, expected in (
        ([nowhere], 1),
        ([*match.seeded_clauses, nowhere], 0),
        (list(match.seeded_clauses), 0),
        ([], 1),
    ):
        moved = match.model_copy(update={"cited_clauses": cited})
        rows = [moved if m is match else m for m in bundle.seed_matches]
        changed = view.PolicyData(bundle.model_copy(update={"seed_matches": rows}), data.documents)
        found = {f.key: f.found for f in view.measure_figures(changed)}["wrong_citations"]
        assert found == wrong_citations(rows) == expected


def test_the_regulation_left_out_is_named_from_the_bundle_and_nowhere_else(data):
    assert view.not_included_lines(data) == ()
    left = view.PolicyData(left_out_bundle(data.bundle), data.documents)
    (line,) = view.not_included_lines(left)
    assert line.name == "SS1/23"
    assert line.sentence.startswith("SS1/23 is not included here: ")
    assert line.sentence.endswith(". To include it:")
    assert len(line.commands) == 2


def test_with_a_regulation_left_out_the_register_sentence_names_only_those_it_holds(data):
    left = view.PolicyData(left_out_bundle(data.bundle), data.documents)
    sentence = view.register_answer(left).sentence
    assert "SS1/23" not in sentence and "DORA and the AI Act" in sentence
    assert [b.key for b in view.picture_view(left).regulations] == ["DORA", "AI-ACT"]
    assert "SS1/23" not in view.picture_answer(left, {}).sentence
