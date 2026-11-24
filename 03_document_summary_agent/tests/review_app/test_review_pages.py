"""The compliance brief's pages over a fake run service, with Starlette's test client."""

from __future__ import annotations

import csv
import html
import io
import re

import pytest
from review_fakes import FakeRuns, examples_review, section_seven_review
from review_fixtures import DANA, TODAY, make_client
from review_helpers import BASE, RUN, decide, settle_everything, text_of

from fsi_common.examples.data import build_examples
from fsi_common.records import Decision, record_digest
from utils.state import CitedFact

ADVICE = "regulatory advice"


def test_the_review_page_answers_in_one_sentence_built_with_its_tiles(client):
    page = client.get(f"{RUN}/review")
    assert (
        "The brief for Harbour Mutual Bank has 2 statements resting on 2 facts. "
        "2 facts and 1 question still need your decision before it can be signed."
        in text_of(page.text)
    )
    values = re.findall(r'tile-value">([^<]+)<', page.text)
    assert values == ["2", "0 of 2", "0 of 1"]


def test_every_statement_and_every_cited_fact_is_on_the_page_and_opens_its_paragraph():
    review = section_seven_review()
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=review)
    c = make_client(runs)
    page = c.get(f"{RUN}/review")
    assert page.text.count('data-hook="statement"') == 5
    for statement in review.request.statements:
        assert statement.text in html.unescape(page.text)
        for cited in statement.facts:
            link = f'href="{RUN}/review?fact={cited.fact.id.replace(":", "%3A")}"'
            assert link in page.text
            opened = c.get(f"{RUN}/review", params={"fact": cited.fact.id})
            number = cited.fact.subject.anchor.removeprefix("para:")
            assert f"Paragraph {number}" in opened.text
            assert f"<mark>{cited.fact.quote}</mark>" in opened.text
            assert cited.fact.provenance.as_of in opened.text


def test_the_source_panel_marks_the_quoted_words_and_names_the_document_and_its_digest(client):
    ex = build_examples()
    page = client.get(f"{RUN}/review", params={"fact": ex.fact_9_3.id})
    assert "Paragraph 9.3" in page.text
    assert "Policy Statement PS26/4: Operational resilience" in page.text
    assert f"<mark>{ex.fact_9_3.quote}</mark>" in page.text
    assert ex.document.digest in page.text


def test_a_quote_that_is_not_in_the_paragraph_is_shown_as_failed_never_hidden(runs):
    review = examples_review()
    cited = review.request.statements[0].facts[0]
    broken = type(cited)(
        fact=cited.fact,
        seen_digest=cited.seen_digest,
        carry=cited.carry,
        unit_text="7.1 A different paragraph altogether.",
    )
    review.request.statements[0].facts[0] = broken  # list is mutable; the model itself is frozen
    runs.replace_review("run-1", review)
    page = make_client(runs).get(f"{RUN}/review", params={"fact": cited.fact.id})
    assert "The quoted words are not in this paragraph" in page.text
    assert "<mark>" not in page.text


def test_the_first_fact_waiting_is_open_when_the_address_names_none(client):
    ex = build_examples()
    page = client.get(f"{RUN}/review")
    assert f"<mark>{ex.fact_7_1.quote}</mark>" in page.text


def test_a_visitor_who_has_not_signed_in_is_asked_to_and_sees_no_decision_form(runs):
    page = make_client(runs, signed_in=None).get(f"{RUN}/review")
    assert "Sign in" in page.text and "to decide on this fact." in page.text
    assert 'data-hook="decision-form"' not in page.text


def test_accepting_a_fact_records_the_persons_decision_and_moves_to_the_next_fact(runs):
    review = runs._runs["run-1"].review
    ex = build_examples()
    c = make_client(runs)
    done = decide(c, review, ex.fact_7_1)
    assert done.status_code == 303
    assert done.headers["location"].startswith(f"{RUN}/review?fact=")
    page = c.get(f"{RUN}/review")
    assert "Accepted by you" in page.text
    assert re.findall(r'tile-value">([^<]+)<', page.text)[1] == "1 of 2"
    assert (
        "Your decision: Accepted by Dana Whitfield, Head of Compliance, on 25 November 2026"
        in text_of(c.get(f"{RUN}/review", params={"fact": ex.fact_7_1.id}).text)
    )


def test_amending_needs_the_persons_wording_and_rejecting_is_recorded(runs):
    review = runs._runs["run-1"].review
    ex = build_examples()
    c = make_client(runs)
    refused = decide(c, review, ex.fact_7_1, outcome="amend")
    assert (
        refused.status_code == 422
        and "Write the amended wording in your own words." in refused.text
    )
    kept = decide(
        c, review, ex.fact_7_1, outcome="amend", amendment="Within 4 hours of classification."
    )
    assert kept.status_code == 303
    rejected = decide(
        c, review, ex.fact_9_3, outcome="reject", reason="The deadline is for another firm."
    )
    assert rejected.status_code == 303
    page = c.get(f"{RUN}/review")
    assert "Amended by you" in page.text and "Rejected by you" in page.text


@pytest.mark.parametrize("reason", ["", "   "])
def test_a_decision_without_the_persons_own_reason_is_refused_in_words(runs, reason):
    review = runs._runs["run-1"].review
    page = decide(make_client(runs), review, build_examples().fact_7_1, reason=reason)
    assert page.status_code == 422
    assert "Write your reason in your own words." in page.text
    assert "Accepted by you" not in make_client(runs).get(f"{RUN}/review").text


def test_a_decision_without_a_signed_in_person_is_refused_and_nothing_is_kept(runs):
    review = runs._runs["run-1"].review
    anonymous = make_client(runs, signed_in=None)
    page = decide(anonymous, review, build_examples().fact_7_1)
    assert page.status_code == 403
    assert "Sign in with your name and role before you decide on a brief." in page.text
    assert "Accepted by you" not in make_client(runs).get(f"{RUN}/review").text


def test_a_decision_on_a_fact_that_is_not_on_the_brief_is_refused(runs):
    review = runs._runs["run-1"].review
    page = decide(make_client(runs), review, build_examples().fact_notes)
    assert page.status_code == 422
    assert "That fact is not on this brief, so nothing was recorded." in page.text


def test_a_stale_brief_is_refused_in_words_and_keeps_the_earlier_decisions(runs):
    old = runs._runs["run-1"].review
    ex = build_examples()
    c = make_client(runs)
    decide(c, old, ex.fact_7_1)
    moved = examples_review()
    moved.request = moved.request.model_copy(update={"brief_digest": "sha256:" + "ab" * 32})
    runs.replace_review("run-1", moved)
    page = decide(c, old, ex.fact_9_3)
    assert page.status_code == 409
    assert "The brief changed after you opened it, so nothing was recorded." in page.text
    assert "Accepted by you" in c.get(f"{RUN}/review").text


def test_a_decision_made_on_a_fact_that_has_since_changed_no_longer_counts(runs):
    ex = build_examples()
    review = runs._runs["run-1"].review
    c = make_client(runs)
    decide(c, review, ex.fact_7_1)
    changed = examples_review()
    first = changed.request.statements[0].facts[0]
    changed.request.statements[0].facts[0] = CitedFact(
        fact=ex.fact_7_1_variant,
        seen_digest=record_digest(ex.fact_7_1_variant),
        carry=first.carry,
        unit_text=first.unit_text,
    )
    runs.replace_review("run-1", changed)
    page = c.get(f"{RUN}/review")
    assert re.findall(r'tile-value">([^<]+)<', page.text)[1] == "0 of 2"


def test_a_carried_decision_shows_as_carried_with_its_date_and_reviewer():
    ex = build_examples()
    runs = FakeRuns()
    runs.add(
        "run-1", "awaiting_review", review=examples_review(earlier={ex.fact_7_1.id: ex.accept_7_1})
    )
    c = make_client(runs)
    page = c.get(f"{RUN}/review", params={"fact": ex.fact_7_1.id})
    assert "Carried: accepted 25 November 2026" in page.text
    assert "Accepted by Dana Whitfield, Head of Compliance, on 25 November 2026" in text_of(
        page.text
    )
    assert re.findall(r'tile-value">([^<]+)<', page.text)[1] == "1 of 2"


def test_an_ask_again_fact_shows_the_earlier_decision_and_what_changed():
    ex = build_examples()
    earlier = Decision.on(
        ex.fact_7_1_variant,
        outcome="accept",
        reason="Reworded requirement read.",
        reviewer=ex.accept_7_1.reviewer,
        date="2026-11-24",
    )
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=examples_review(earlier={ex.fact_7_1.id: earlier}))
    page = make_client(runs).get(f"{RUN}/review", params={"fact": ex.fact_7_1.id})
    assert 'data-hook="ask-again"' in page.text
    assert "Accepted by Dana Whitfield, Head of Compliance, on 24 November 2026" in text_of(
        page.text
    )
    assert "Since then these changed: Requirement." in text_of(page.text)
    assert "Needs a person" in page.text
    assert re.findall(r'tile-value">([^<]+)<', page.text)[1] == "0 of 2"


def test_an_open_question_is_answered_or_accepted_as_an_assumption_in_the_persons_words(runs):
    review = runs._runs["run-1"].review
    q = review.question
    c = make_client(runs)
    body = {"brief_digest": review.request.brief_digest, "question_id": q.id}
    refused = c.post(f"{RUN}/answer", data={**body, "answer": "Yes", "reason": " "})
    assert (
        refused.status_code == 422
        and "Write what the answer rests on in your own words." in refused.text
    )
    done = c.post(
        f"{RUN}/answer",
        data={**body, "answer": "Both were made in 2024.", "reason": "Contracts register."},
    )
    assert done.status_code == 303
    page = c.get(f"{RUN}/review", params={"tab": "questions"})
    assert "Answered by you" in page.text and "Both were made in 2024." in page.text
    c.post(f"{RUN}/assume", data={**body, "words": "Treat both as made before 2027."})
    page = c.get(f"{RUN}/review", params={"tab": "questions"})
    assert (
        "Accepted by you as an assumption" in page.text
        and "Both were made in 2024." not in page.text
    )
    assert re.findall(r'tile-value">([^<]+)<', page.text)[2] == "1 of 1"


def test_an_assumption_without_words_is_refused(runs):
    review = runs._runs["run-1"].review
    page = make_client(runs).post(
        f"{RUN}/assume",
        data={
            "brief_digest": review.request.brief_digest,
            "question_id": review.question.id,
            "words": "",
        },
    )
    assert page.status_code == 422 and "Write the assumption in your own words." in page.text


def test_the_brief_cannot_be_signed_until_every_fact_and_question_is_settled(runs):
    review = runs._runs["run-1"].review
    c = make_client(runs)
    page = c.get(f"{RUN}/review", params={"tab": "signoff"})
    assert (
        "The brief cannot be signed yet: 2 facts without a decision and 1 question not "
        "answered or accepted." in page.text
    )
    refused = c.post(
        f"{RUN}/sign", data={"brief_digest": review.request.brief_digest, "outcome": "signed"}
    )
    assert refused.status_code == 422 and "The brief cannot be signed yet" in refused.text
    assert runs.submitted == []


def test_signing_sends_the_persons_decisions_and_sign_off_to_the_engine_and_shows_the_record(runs):
    c = make_client(runs)
    review = settle_everything(c, runs)
    page = c.get(f"{RUN}/review", params={"tab": "signoff"})
    assert "Every fact and question is settled, so it is ready for you to sign." in text_of(
        c.get(f"{RUN}/review").text
    )
    assert "cannot be signed yet" not in page.text
    done = c.post(
        f"{RUN}/sign", data={"brief_digest": review.request.brief_digest, "outcome": "signed"}
    )
    assert done.status_code == 303 and done.headers["location"] == f"{RUN}/signed"
    [(thread, response)] = runs.submitted
    assert thread == "run-1"
    assert response.reviewer == DANA
    assert response.sign_off.outcome == "signed"
    assert response.sign_off.brief_digest == review.request.brief_digest
    assert response.sign_off.reviewer == DANA and response.sign_off.date == TODAY
    assert [a.words for a in response.sign_off.assumptions] == ["Treat both as made before 2027."]
    assert {d.subject_id for d in response.decisions} == {f.id for f in review.facts.values()}
    assert all(d.reviewer == DANA and d.date == TODAY for d in response.decisions)
    record = c.get(f"{RUN}/signed")
    assert (
        "Dana Whitfield, Head of Compliance, signed the brief for Harbour Mutual Bank."
        in record.text
    )
    assert review.request.brief_digest in record.text
    assert "25 November 2026" in record.text and "Treat both as made before 2027." in record.text
    assert record.text.count("<tr>") == 3  # heading row and one row for each decision


def test_a_brief_can_be_returned_with_the_persons_reason_even_before_it_is_settled(runs):
    review = runs._runs["run-1"].review
    c = make_client(runs)
    body = {"brief_digest": review.request.brief_digest, "outcome": "returned"}
    refused = c.post(f"{RUN}/sign", data=body)
    assert (
        refused.status_code == 422
        and "Write why you are returning the brief in your own words." in refused.text
    )
    done = c.post(f"{RUN}/sign", data={**body, "reason": "The deadlines need another reading."})
    assert done.status_code == 303
    assert runs.submitted[0][1].sign_off.outcome == "returned"
    assert runs.submitted[0][1].sign_off.reason == "The deadlines need another reading."
    assert "returned the brief for Harbour Mutual Bank." in c.get(f"{RUN}/signed").text


def test_a_brief_with_a_rejected_fact_can_be_returned_but_not_signed(runs):
    review = runs._runs["run-1"].review
    ex = build_examples()
    c = make_client(runs)
    decide(c, review, ex.fact_7_1)
    decide(c, review, ex.fact_9_3, outcome="reject", reason="Wrong deadline.")
    c.post(
        f"{RUN}/assume",
        data={
            "brief_digest": review.request.brief_digest,
            "question_id": review.question.id,
            "words": "Assumed.",
        },
    )
    page = c.get(f"{RUN}/review")
    assert "You rejected 1 fact, so the brief can be returned but not signed." in text_of(page.text)
    refused = c.post(
        f"{RUN}/sign", data={"brief_digest": review.request.brief_digest, "outcome": "signed"}
    )
    assert (
        refused.status_code == 422 and "You rejected 1 fact that the brief cites." in refused.text
    )


def test_signing_without_a_signed_in_person_is_refused(runs):
    review = runs._runs["run-1"].review
    page = make_client(runs, signed_in=None).post(
        f"{RUN}/sign", data={"brief_digest": review.request.brief_digest, "outcome": "signed"}
    )
    assert page.status_code == 403 and runs.submitted == []


def test_the_facts_table_lists_every_fact_sorts_and_exports_the_same_rows(client):
    page = client.get(f"{RUN}/facts")
    assert page.text.count("<tr>") == 3
    assert (
        "2 facts support the brief for Harbour Mutual Bank; 2 still need a decision." in page.text
    )
    down = client.get(f"{RUN}/facts.csv?sort=source&dir=desc")
    rows = list(csv.reader(io.StringIO(down.text)))
    assert rows[0][:2] == ["Source", "Kind"]
    assert [r[0] for r in rows[1:]] == ["Paragraph 9.3", "Paragraph 7.1"]
    assert "attachment" in down.headers["content-disposition"]
    shown = [
        m
        for m in re.findall(
            r'<td>\s*<a href="[^"]+" title="[^"]+">([^<]+)</a>',
            client.get(f"{RUN}/facts?sort=source&dir=desc").text,
        )
    ]
    assert shown == ["Paragraph 9.3", "Paragraph 7.1"]


def test_the_advice_sentence_is_on_no_page_of_the_topic(runs):
    runs.add("run-2", "signed", review=examples_review())
    runs.add(
        "run-3", "failed", request={"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "x"}
    )
    runs.add(
        "run-4", "running", request={"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "x"}
    )
    c = make_client(runs)
    for path in (
        f"{BASE}/",
        f"{BASE}/runs/run-1/review",
        f"{RUN}/review?tab=questions",
        f"{RUN}/review?tab=signoff",
        f"{RUN}/facts",
        f"{BASE}/runs/run-3",
        f"{BASE}/runs/run-4",
    ):
        assert ADVICE not in c.get(path).text.lower(), path


def test_no_page_offers_the_machine_a_way_to_approve(client):
    for path in (f"{RUN}/review", f"{RUN}/review?tab=questions", f"{RUN}/review?tab=signoff"):
        html = client.get(path).text.lower()
        assert "auto-approve" not in html and "approve" not in html, path
