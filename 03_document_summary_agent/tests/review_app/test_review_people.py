"""Whose decision is whose: held decisions belong to the person who made them, and pages say so."""

from __future__ import annotations

import csv
import io
import re

from review_fakes import FakeRuns, examples_review
from review_fixtures import DANA, make_client
from review_helpers import (
    ALEX,
    BASE,
    RUN,
    SAM,
    accept_on,
    assume,
    decide,
    finish,
    settle_everything,
    switch_to,
    text_of,
)

from fsi_common.examples.data import build_examples

EX = build_examples()


def tiles(page):
    return re.findall(r'tile-value">([^<]+)<', page.text)


def test_a_second_person_sees_none_of_the_first_persons_decisions_as_theirs(runs):
    c = make_client(runs)
    review = runs._runs["run-1"].review
    decide(c, review, EX.fact_7_1)
    assume(c, review)
    assert "Accepted by you" in c.get(f"{RUN}/review").text
    switch_to(c, SAM)
    page = c.get(f"{RUN}/review")
    assert "Accepted by you" not in page.text
    assert tiles(page) == ["2", "0 of 2", "0 of 1"]
    assert "Needs a person" in page.text
    assert "by you" not in c.get(f"{RUN}/facts").text
    assert "Accepted by you" not in c.get(f"{RUN}/review", params={"tab": "questions"}).text
    refused = c.post(
        f"{RUN}/sign", data={"brief_digest": review.request.brief_digest, "outcome": "signed"}
    )
    assert refused.status_code == 422
    assert (
        "The brief cannot be signed yet: 2 facts without a decision and 1 question not answered "
        "or accepted." in refused.text
    )
    assert runs.submitted == []
    switch_to(c, DANA)
    assert tiles(c.get(f"{RUN}/review")) == ["2", "1 of 2", "1 of 1"]


def test_each_person_signs_only_their_own_decisions(runs):
    c = make_client(runs)
    review = runs._runs["run-1"].review
    settle_everything(c, runs)  # Dana decides both facts and accepts the question as an assumption
    switch_to(c, SAM)
    decide(c, review, EX.fact_7_1)
    assume(c, review)
    body = {"brief_digest": review.request.brief_digest, "outcome": "signed"}
    refused = c.post(f"{RUN}/sign", data=body)
    assert refused.status_code == 422
    assert "The brief cannot be signed yet: 1 fact without a decision." in refused.text
    assert "made by" not in refused.text
    decide(c, review, EX.fact_9_3)
    assert c.post(f"{RUN}/sign", data=body).status_code == 303
    [(_, response)] = runs.submitted
    assert response.reviewer == SAM and response.sign_off.reviewer == SAM
    assert {d.reviewer for d in response.decisions} == {SAM}
    assert len(response.decisions) == 2


def test_a_finished_brief_shows_each_decision_under_the_name_of_the_person_who_made_it():
    runs = FakeRuns()
    finish(
        runs,
        "run-1",
        [
            accept_on(EX.fact_7_1, DANA, "2026-11-24"),
            accept_on(EX.fact_9_3, SAM, "2026-11-25"),
        ],
        SAM,
        on="2026-11-25",
    )
    dana_line = "Accepted by Dana Whitfield, Head of Compliance, on 24 November 2026"
    for viewer in (ALEX, None):
        c = make_client(runs, signed_in=viewer)
        facts = text_of(c.get(f"{RUN}/facts").text)
        assert dana_line in facts
        assert "Accepted by Sam Okoye, Compliance Officer, on 25 November 2026" in facts
        assert " by you" not in facts
        signed = c.get(f"{RUN}/signed")
        assert " by you" not in signed.text
        rows = text_of(signed.text)
        assert (
            "Dana Whitfield, Head of Compliance" in rows and "Sam Okoye, Compliance Officer" in rows
        )
    sam = text_of(make_client(runs, signed_in=SAM).get(f"{RUN}/facts").text)
    assert "Accepted by you, on 25 November 2026" in sam
    assert dana_line in sam
    dana = text_of(make_client(runs, signed_in=DANA).get(f"{RUN}/facts").text)
    assert "Accepted by you, on 24 November 2026" in dana
    assert "Accepted by Sam Okoye, Compliance Officer, on 25 November 2026" in dana


def test_a_carried_decision_in_the_facts_table_names_its_reviewer_and_gives_a_long_date():
    runs = FakeRuns()
    runs.add(
        "run-1",
        "awaiting_review",
        review=examples_review(earlier={EX.fact_7_1.id: EX.accept_7_1}),
    )
    for viewer, who in ((DANA, "you"), (SAM, "Dana Whitfield, Head of Compliance")):
        page = make_client(runs, signed_in=viewer).get(f"{RUN}/facts")
        words = text_of(page.text)
        assert f"Accepted by {who}, on 25 November 2026, carried from an earlier review" in words
        assert "2026-11-25" not in page.text


def _two_decisions_on_one_fact(signer, *, first_date="2026-11-24", second_date="2026-11-25"):
    runs = FakeRuns()
    finish(
        runs,
        "run-1",
        [
            accept_on(EX.fact_7_1, DANA, first_date),
            accept_on(
                EX.fact_7_1, SAM, second_date, outcome="amend", amendment="Within four hours."
            ),
            accept_on(EX.fact_9_3, SAM, second_date),
        ],
        signer,
        on=second_date,
    )
    return runs


def _facts_row(page, paragraph):
    return next(
        r
        for r in re.findall(r"<tr>.*?</tr>", page.text, flags=re.DOTALL)
        if f">Paragraph {paragraph}<" in r
    )


def test_where_a_fact_has_two_decisions_the_pages_show_the_sign_off_reviewers(runs):
    runs = _two_decisions_on_one_fact(SAM)
    c = make_client(runs, signed_in=ALEX)
    signed = c.get(f"{RUN}/signed")
    rows = re.findall(r"<tr>.*?</tr>", signed.text, flags=re.DOTALL)
    assert len(rows) == 3  # the heading row and one row for each fact
    about_71 = [r for r in rows if "Paragraph 7.1" in r]
    assert len(about_71) == 1
    assert "Amended: Within four hours." in text_of(about_71[0])
    assert "Sam Okoye, Compliance Officer" in about_71[0]
    assert "Dana Whitfield" not in signed.text.split("Decisions made on the brief")[1]
    assert tiles(signed)[1] == "2"  # two decisions recorded, one for each fact
    facts = c.get(f"{RUN}/facts")
    row = text_of(_facts_row(facts, "7.1"))
    assert "Amended by Sam Okoye, Compliance Officer, on 25 November 2026" in row
    assert "Dana" not in row
    exported = list(csv.reader(io.StringIO(c.get(f"{RUN}/decisions.csv").text)))
    assert len(exported) == 3
    assert [r[0] for r in exported[1:]].count("Paragraph 7.1") == 1
    assert {r[3] for r in exported[1:]} == {"Sam Okoye, Compliance Officer"}


def test_where_the_sign_off_reviewer_made_none_the_latest_decision_by_date_is_shown():
    runs = _two_decisions_on_one_fact(ALEX)
    c = make_client(runs, signed_in=ALEX)
    row = text_of(_facts_row(c.get(f"{RUN}/facts"), "7.1"))
    assert "Amended by Sam Okoye, Compliance Officer, on 25 November 2026" in row
    runs = _two_decisions_on_one_fact(ALEX, first_date="2026-11-26", second_date="2026-11-25")
    row = text_of(_facts_row(make_client(runs, signed_in=ALEX).get(f"{RUN}/facts"), "7.1"))
    assert "Accepted by Dana Whitfield, Head of Compliance, on 26 November 2026" in row


def test_where_the_sign_off_reviewer_decided_on_another_day_than_the_sign_off_the_latest_wins():
    runs = FakeRuns()
    finish(
        runs,
        "run-1",
        [
            accept_on(EX.fact_7_1, SAM, "2026-11-24"),
            accept_on(EX.fact_7_1, DANA, "2026-11-26", outcome="reject"),
            accept_on(EX.fact_9_3, SAM, "2026-11-25"),
        ],
        SAM,
        on="2026-11-25",
        outcome="returned",
    )
    row = text_of(_facts_row(make_client(runs, signed_in=SAM).get(f"{RUN}/facts"), "7.1"))
    assert "Rejected by Dana Whitfield, Head of Compliance, on 26 November 2026" in row
    assert BASE
