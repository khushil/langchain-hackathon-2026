"""Helpers the page tests share: addresses, decision posts, settled runs and finished runs."""

from __future__ import annotations

import re

from review_fakes import FakeRuns, examples_review, section_seven_review
from review_fixtures import DANA, TODAY

from fsi_common.app.session import SessionCodec
from fsi_common.examples.data import build_examples
from fsi_common.records import Decision, Person, SignOff
from utils.state import ReviewResponse

BASE = "/compliance-brief"
RUN = f"{BASE}/runs/run-1"
MOVED_DIGEST = "sha256:" + "ab" * 32


def text_of(html: str) -> str:
    """Return a page's text with the tags removed and the white space folded."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def decide(client, review, fact, **fields):
    """Post a decision on a fact, as the reviewer's form does."""
    body = {
        "brief_digest": review.request.brief_digest,
        "fact_id": fact.id,
        "outcome": "accept",
        "reason": "The quote matches the paragraph.",
        **fields,
    }
    return client.post(f"{RUN}/decide", data=body)


def assume(client, review, words="Treat both as made before 2027."):
    """Accept the brief's open question as an assumption."""
    return client.post(
        f"{RUN}/assume",
        data={
            "brief_digest": review.request.brief_digest,
            "question_id": review.question.id,
            "words": words,
        },
    )


def settle_everything(client, runs):
    """Decide both facts and accept the question as an assumption, as one signed-in person."""
    review = runs._runs["run-1"].review
    ex = build_examples()
    decide(client, review, ex.fact_7_1)
    decide(client, review, ex.fact_9_3)
    assume(client, review)
    return review


def move_the_brief(runs, thread="run-1"):
    """Move a run's brief on, as a rerun would, so that its digest is no longer the one shown."""
    moved = examples_review()
    moved.request = moved.request.model_copy(update={"brief_digest": MOVED_DIGEST})
    runs.replace_review(thread, moved)
    return moved


SAM = Person(name="Sam Okoye", role="Compliance Officer")
ALEX = Person(name="Alex Reid", role="Head of Operational Resilience")


def switch_to(client, person):
    """Sign the client in as another person, as the sign-in form would."""
    client.cookies.set(client.app.state.cookie_name, SessionCodec(b"test-secret").encode(person))


def finish(runs, thread, decisions, signer, *, on, outcome="signed", status=None):
    """Put a finished run in: the given decisions and a sign-off by one person.

    Args:
        runs: The fake run service.
        thread: The run's id.
        decisions: The decisions the run's state holds, in order.
        signer: The person whose sign-off ends the run.
        on: The sign-off's date.
        outcome: ``signed`` or ``returned``.
        status: The run's status; the outcome when absent.
    """
    review = examples_review()
    runs.add(thread, "awaiting_review", review=review)
    run = runs._runs[thread]
    assumptions = [{"question_id": review.question.id, "words": "Treat both as made before 2027."}]
    run.state["decisions"] = {d.id: d.to_json() for d in decisions}
    run.state["sign_off"] = SignOff.build(
        brief_id=review.request.brief_id,
        brief_digest=review.request.brief_digest,
        reviewer=signer,
        date=on,
        outcome=outcome,
        assumptions=assumptions,
        reason="Returned for a rewrite." if outcome == "returned" else None,
    ).to_json()
    run.status = status or outcome
    return review


def accept_on(fact, person, on, outcome="accept", **fields):
    """Return a person's decision on a fact, made on a date."""
    return Decision.on(
        fact, outcome=outcome, reason=f"Read by {person.name}.", reviewer=person, date=on, **fields
    )


def runs_for_every_page() -> FakeRuns:
    """Hold one run in each state: waiting for review, signed, being written and stopped."""
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=examples_review())
    finish(runs, "run-2", [], DANA, on=TODAY)
    runs.add(
        "run-3",
        "running",
        request={"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "x", "sections": ["7"]},
    )
    runs.add("run-4", "failed", request=runs._runs["run-3"].request, error="No answer.")
    return runs


def signed_section_seven_run() -> FakeRuns:
    """Hold section 7's brief signed by Dana Whitfield, with a decision on every fact."""
    runs = FakeRuns()
    review = section_seven_review()
    runs.add("run-1", "awaiting_review", review=review)
    facts = [c.fact for s in review.request.statements for c in s.facts]
    decisions = [
        Decision.on(f, outcome="accept", reason="Read.", reviewer=DANA, date=TODAY) for f in facts
    ]
    sign_off = SignOff.build(
        brief_id=review.request.brief_id,
        brief_digest=review.request.brief_digest,
        reviewer=DANA,
        date=TODAY,
        outcome="signed",
        assumptions=[{"question_id": review.question.id, "words": "Treat the services as listed."}],
    )
    runs.submit("run-1", ReviewResponse(reviewer=DANA, decisions=decisions, sign_off=sign_off))
    return runs
