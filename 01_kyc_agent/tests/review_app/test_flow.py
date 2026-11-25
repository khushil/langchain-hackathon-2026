"""Recording through the routes: decisions, answers, refusals, sign-off and carry-over."""

import re

import pytest
from kyc_fakes import ScriptedReader, reading_of
from support import (
    BASE,
    DANA,
    SAM,
    SMALL,
    make_client,
    new_runs,
    settle_all,
    start_run,
    switch_to,
    text_of,
)

from workflow.runs import KycRuns


@pytest.fixture()
def batch():
    runs = new_runs()
    thread = start_run(runs, SMALL)
    return runs, thread, make_client(runs)


def run(thread, *parts):
    return "/".join([BASE, "runs", thread, *parts])


def proposal_id(runs, thread, customer):
    request = runs.review_request(thread)
    return next(
        c.fact.id
        for s in request.statements
        for c in s.facts
        if c.fact.kind == "proposal" and c.fact.subject.anchor == f"row:{customer}"
    ), request


def decide(client, runs, thread, customer, **fields):
    fact_id, request = proposal_id(runs, thread, customer)
    body = {
        "brief_digest": request.brief_digest,
        "fact_id": fact_id,
        "customer": customer,
        "outcome": "accept",
        "reason": "Checked against the lists.",
        **fields,
    }
    return client.post(run(thread, "decide"), data=body)


def test_a_decision_is_recorded_shown_as_the_persons_own_and_leads_to_the_next(batch):
    runs, thread, client = batch
    done = decide(client, runs, thread, "CUST-001")
    assert done.status_code == 303
    assert done.headers["location"].endswith("/applications/CUST-003")
    page = text_of(client.get(run(thread, "applications", "CUST-001")).text)
    assert "Your decision: Accepted by you, on 25 November 2026" in page
    assert "Your reason: Checked against the lists." in page
    assert "1 of 4" in text_of(client.get(run(thread, "review")).text)


def test_a_refusal_keeps_what_was_typed_and_says_the_reason_once(batch):
    runs, thread, client = batch
    refused = decide(
        client, runs, thread, "CUST-003", outcome="amend", reason="Because of the dates."
    )
    assert refused.status_code == 422
    html = refused.text
    assert html.count("Write the amended wording in your own words.") == 1
    assert "Because of the dates." in html
    assert re.search(r'value="amend"\s+checked', html)


def test_a_decision_on_a_changed_batch_is_refused_and_nothing_is_recorded(batch):
    runs, thread, client = batch
    fact_id, request = proposal_id(runs, thread, "CUST-001")
    stale = client.post(
        run(thread, "decide"),
        data={
            "brief_digest": "sha256:" + "0" * 64,
            "fact_id": fact_id,
            "outcome": "accept",
            "reason": "x",
        },
    )
    assert stale.status_code == 409 and "changed after you opened it" in stale.text
    assert "0 of 4" in text_of(client.get(run(thread, "review")).text)


def test_nobody_signed_in_can_record_nothing(batch):
    runs, thread, _ = batch
    nobody = make_client(runs, signed_in=None)
    fact_id, request = proposal_id(runs, thread, "CUST-001")
    for route, body in (
        ("decide", {"fact_id": fact_id, "outcome": "accept", "reason": "x"}),
        ("sign", {"outcome": "returned", "reason": "x"}),
    ):
        refused = nobody.post(
            run(thread, route), data={"brief_digest": request.brief_digest, **body}
        )
        assert refused.status_code == 403 and "Sign in with your name and role" in refused.text


def test_no_one_act_accepts_many_proposals_and_each_is_decided_in_its_own_words(batch):
    runs, thread, client = batch
    request = runs.review_request(thread)
    html = client.get(run(thread, "review")).text
    assert "Accept the" not in text_of(html) and "settled-form" not in html
    answer = client.post(
        run(thread, "settled"),
        data={"brief_digest": request.brief_digest, "reason": "Read each one."},
    )
    assert answer.status_code in (404, 405)
    assert not runs.result(thread).get("decisions")


def test_an_answer_changes_the_picture_and_the_question_leaves_the_waiting_count(batch):
    runs, thread, client = batch
    request = runs.review_request(thread)
    question = next(q for q in request.open_questions if "CUST-018" in q.about.anchor)
    done = client.post(
        run(thread, "answer"),
        data={
            "brief_digest": request.brief_digest,
            "question_id": question.id,
            "customer": "CUST-018",
            "answer": "A different person.",
            "reason": "The dates of birth are eleven years apart.",
        },
    )
    assert done.status_code == 303 and done.headers["location"].endswith("/applications/CUST-018")
    page = text_of(client.get(run(thread, "applications", "CUST-018")).text)
    assert "Answered by you, on 25 November 2026" in page and "1 of 1" in page
    assert "Given by Answered" not in page
    assert "Recorded Answered by you, on 25 November 2026" in page
    batch_page = client.get(run(thread, "review")).text
    assert 'data-state="answered"' in batch_page


def test_an_assumption_settles_a_question_and_is_the_persons_own(batch):
    runs, thread, client = batch
    request = runs.review_request(thread)
    question = request.open_questions[0]
    customer = question.about.anchor.partition(":")[2].partition("/")[0]
    done = client.post(
        run(thread, "assume"),
        data={
            "brief_digest": request.brief_digest,
            "question_id": question.id,
            "words": "Assume so.",
        },
    )
    assert done.status_code == 303
    page = text_of(client.get(run(thread, "applications", customer)).text)
    assert "Accepted by you as an assumption" in page and "Your assumption Assume so." in page
    blank = client.post(
        run(thread, "assume"),
        data={"brief_digest": request.brief_digest, "question_id": question.id, "words": " "},
    )
    assert blank.status_code == 422


def test_the_batch_is_signed_through_the_review_and_the_signed_page_shows_the_record(batch):
    runs, thread, client = batch
    too_soon = client.post(
        run(thread, "sign"),
        data={"brief_digest": runs.review_request(thread).brief_digest, "outcome": "signed"},
    )
    assert too_soon.status_code == 422
    assert text_of(too_soon.text).count("The batch cannot be signed yet") == 1
    settle_all(client, runs, thread)
    digest = runs.review_request(thread).brief_digest
    signed = client.post(run(thread, "sign"), data={"brief_digest": digest, "outcome": "signed"})
    assert signed.status_code == 303 and signed.headers["location"] == run(thread, "signed")
    assert runs.status(thread) == "signed"
    html = client.get(run(thread, "signed")).text
    text = text_of(html)
    assert "Dana Whitfield, Head of Compliance, signed the batch of 4 applications." in text
    assert "Signed" in text and "25 November 2026" in text
    main = html.split("<main", 1)[1]
    assert "<form" not in main and "<button" not in main
    assert "Accepted" in text and "A different person." in text
    assert client.get(run(thread, "review")).headers["location"] == run(thread)
    mine = text_of(client.get(run(thread, "applications", "CUST-018")).text)
    assert "Answered by you, on 25 November 2026" in mine
    switch_to(client, SAM)
    again = text_of(client.get(run(thread, "applications", "CUST-018")).text)
    assert "Answered by Dana Whitfield, Head of Compliance, on 25 November 2026" in again
    assert "Answer A different person." in again


def test_a_batch_can_be_returned_with_a_reason_and_not_without_one(batch):
    runs, thread, client = batch
    digest = runs.review_request(thread).brief_digest
    blank = client.post(run(thread, "sign"), data={"brief_digest": digest, "outcome": "returned"})
    assert blank.status_code == 422 and "why you are returning" in blank.text
    done = client.post(
        run(thread, "sign"),
        data={"brief_digest": digest, "outcome": "returned", "reason": "Read the lists again."},
    )
    assert done.status_code == 303
    assert "returned the batch" in text_of(client.get(run(thread, "signed")).text)


def test_a_batch_cannot_be_signed_on_another_persons_decisions(batch):
    runs, thread, client = batch
    settle_all(client, runs, thread)
    switch_to(client, SAM)
    digest = runs.review_request(thread).brief_digest
    refused = client.post(run(thread, "sign"), data={"brief_digest": digest, "outcome": "signed"})
    assert refused.status_code == 422 and "proposals without a decision" in refused.text


def test_a_later_batch_carries_a_decision_and_asks_again_with_the_difference_named():
    runs = new_runs()
    client = make_client(runs)
    first = start_run(runs, SMALL)
    settle_all(client, runs, first)
    digest = runs.review_request(first).brief_digest
    client.post(run(first, "sign"), data={"brief_digest": digest, "outcome": "signed"})
    wrong = reading_of("CUST-016")
    wrong = wrong.model_copy(
        update={"date_of_birth": wrong.date_of_birth.model_copy(update={"value": "1971-04-18"})}
    )
    later = KycRuns(models=ScriptedReader(readings={"CUST-016": wrong}), store=runs._graph.store)
    second = start_run(later, SMALL)
    both = make_client(later)
    carried = text_of(both.get(run(second, "applications", "CUST-001")).text)
    assert "Accepted by you, on 25 November 2026" in carried
    assert "carried" in both.get(run(second, "applications", "CUST-001")).text
    asked = both.get(run(second, "applications", "CUST-016")).text
    assert 'data-hook="ask-again"' in asked
    assert "Since then these changed:" in text_of(asked) and "Settled by the checks" in text_of(
        asked
    )
    table = text_of(both.get(run(second, "review")).text)
    assert "carried from an earlier review" in table


def test_the_application_page_of_a_run_that_is_not_there_or_not_ready_is_a_404():
    runs = new_runs()
    client = make_client(runs)
    assert client.get(run("none", "applications", "CUST-001")).status_code == 404


def test_the_decisions_csv_holds_every_decision_of_a_signed_batch(batch):
    runs, thread, client = batch
    settle_all(client, runs, thread)
    digest = runs.review_request(thread).brief_digest
    client.post(run(thread, "sign"), data={"brief_digest": digest, "outcome": "signed"})
    lines = client.get(run(thread, "decisions.csv")).text.strip().splitlines()
    assert lines[0] == "About,Decision,Reviewer,Date,Reason" and len(lines) == 1 + 4 + 2
    assert DANA.name in client.get(run(thread, "decisions.csv")).text
