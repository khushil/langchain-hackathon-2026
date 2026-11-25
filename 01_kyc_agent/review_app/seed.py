"""The topic's starting work: a batch waiting for a reviewer and a batch signed by a fictional one.

Both batches are runs of the real workflow on all the applications. The signed batch is taken
through the application's own review routes by a fictional reviewer, so every decision, answer,
accepted assumption and the sign-off are built by the review route from the wording in
``seed_fixture`` and nowhere else. Nothing here decides for anyone.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import replace
from pathlib import Path

from starlette.testclient import TestClient

from context.reader import read_applications
from fsi_common.app import AppConfig, SeedError, create_app
from fsi_common.app.session import SessionCodec
from fsi_common.ids import digest_bytes, digest_json
from fsi_common.records import Person
from review_app.context import PREFIX, Services, runs_of
from review_app.seed_fixture import DECISIONS, QUESTIONS
from utils.models import recordings_dir
from utils.records import customer_of_anchor

REVIEWER = Person(name="Dana Whitfield", role="Head of Compliance")
SEED_DATE = "2026-11-24"
"""The date on every seeded decision, fixed so that starting twice gives the same records."""
SECRET = b"starting-work"
SEED_NAME = "kyc-onboarding"
MARKER_FILE = "seeded.json"
"""The file a finished seed leaves in a state folder: the seed's name and what it was made from."""
WAIT_SECONDS = 180.0
POLL_SECONDS = 0.1


def seed_kyc_onboarding(services: Services) -> None:
    """Make a batch that waits for a reviewer and a batch that is signed.

    When the services keep their state in a folder, a finished seed leaves a marker there, and a
    later start that finds the marker matching leaves the batches as they are, so a restart adds
    no second copy. A folder that holds batches with no marker, or a marker made from other
    recordings or another fixture, is refused. The waiting batch is made first: the engine carries
    a signed batch's decisions into later runs on the same customers, so a batch made after the
    signed one would arrive already decided.

    Args:
        services: The run service and held decisions of the topic being served.

    Raises:
        SeedError: If a run stops, the fixture does not match what the batch holds, the review
            route refuses a decision or the sign-off, or the state folder holds batches this seed
            did not make.
    """
    from review_app.plugin import build_plugin  # the plug-in imports this module for its seed

    if _already_seeded(services):
        return
    shadow = replace(services, today=lambda: SEED_DATE)
    app = create_app(AppConfig(secret=SECRET, topic_folders=()), topics=[build_plugin(shadow)])
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(app.state.cookie_name, SessionCodec(SECRET).encode(REVIEWER))
    _start_and_wait(client, services)
    signed = _start_and_wait(client, services)
    _review_and_sign(client, services, signed)
    _write_marker(services)


def seed_identity() -> str:
    """Return what the seed is made from: its fixture, the applications and every recorded call."""
    folder = recordings_dir(os.environ)
    recordings = {p.name: digest_bytes(p.read_bytes()) for p in sorted(folder.glob("*.json"))}
    return digest_json(
        {
            "fixture": [SEED_DATE],
            "decisions": [[d.customer, d.outcome, d.reason, d.amendment] for d in DECISIONS],
            "questions": [
                [q.customer, q.place, q.answer, q.reason, q.assumption] for q in QUESTIONS
            ],
            "recordings": recordings,
        }
    )


def _already_seeded(services: Services) -> bool:
    """Say whether this state folder was seeded from these recordings; refuse one that was not."""
    folder = services.state_dir
    if folder is None:
        return False
    marker = Path(folder) / MARKER_FILE
    if not marker.exists() and not runs_of(services).list_runs():
        return False
    try:
        held = json.loads(marker.read_text())
    except (OSError, ValueError):
        held = None
    if held == {"seed": SEED_NAME, "digest": seed_identity()}:
        return True
    raise SeedError(
        f"The state folder {folder} holds batches that this start did not make from these "
        f"recordings, or a seed that stopped partway; delete the folder {folder} to start afresh."
    )


def _write_marker(services: Services) -> None:
    folder = services.state_dir
    if folder is None:
        return
    held = json.dumps({"seed": SEED_NAME, "digest": seed_identity()})
    staging = Path(folder) / f"{MARKER_FILE}.part"
    try:
        staging.write_text(held)
        os.replace(staging, Path(folder) / MARKER_FILE)
    except OSError as exc:
        raise SeedError(
            f"The starting work was made, but its marker could not be written in {folder}: {exc}"
        ) from exc


def _start_and_wait(client: TestClient, services: Services) -> str:
    """Start a batch of every application through the start route and wait for its review."""
    customers = [u.anchor.partition(":")[2] for u in read_applications().units]
    started = client.post(f"{PREFIX}/runs", data={"customers": customers})
    if started.status_code != 303:
        raise SeedError(f"The start route answered {started.status_code} instead of starting.")
    thread = started.headers["location"].rsplit("/", 1)[1]
    runs = runs_of(services)
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        status = runs.status(thread)
        if status == "awaiting_review":
            return thread
        if status != "running":
            reason = runs.error(thread) or "the engine gave no reason"
            raise SeedError(f"The batch stopped before its review: {reason}.")
        time.sleep(POLL_SECONDS)
    raise SeedError(f"The batch did not reach its review within {WAIT_SECONDS:g} seconds.")


def _place(question) -> str:
    return question.about.anchor.partition("/")[2] or "relation"


def _check_fixture(request) -> None:
    """Refuse a recorded batch the fixture was not written for, naming each thing that changed."""
    proposals = {
        customer_of_anchor(c.fact.subject.anchor): c.fact
        for s in request.statements
        for c in s.facts
        if c.fact.kind == "proposal"
    }
    wanted = {d.customer for d in DECISIONS}
    asked = {(customer_of_anchor(q.about.anchor), _place(q)) for q in request.open_questions}
    held = {(q.customer, q.place) for q in QUESTIONS}
    problems = []
    if set(proposals) - wanted:
        problems.append(
            f"proposals with no decision in the seed: {sorted(set(proposals) - wanted)}"
        )
    if wanted - set(proposals):
        problems.append(
            f"decisions in the seed for applications not on the batch: "
            f"{sorted(wanted - set(proposals))}"
        )
    if asked - held:
        problems.append(f"questions with no answer in the seed: {sorted(asked - held)}")
    if held - asked:
        problems.append(
            f"answers in the seed for questions not on the batch: {sorted(held - asked)}"
        )
    if problems:
        raise SeedError(
            "The batch is not the one the seed's decisions were written for. "
            + ". ".join(problems)
            + "."
        )


def _expect_redirect(response, what: str) -> None:
    if response.status_code != 303:
        problem = re.search(r'data-hook="form-problem">(.*?)</p>', response.text, re.S)
        words = " ".join(re.sub(r"<[^>]+>", " ", problem.group(1)).split()) if problem else ""
        raise SeedError(
            f"The review route refused {what} with {response.status_code}: "
            f"{words or 'no reason given on the page'}"
        )


def _review_and_sign(client: TestClient, services: Services, thread: str) -> None:
    """Record the fixture's decisions through the review routes, then sign through them."""
    request = runs_of(services).review_request(thread)
    _check_fixture(request)
    run = f"{PREFIX}/runs/{thread}"
    digest = request.brief_digest
    proposals = {
        customer_of_anchor(c.fact.subject.anchor): c.fact.id
        for s in request.statements
        for c in s.facts
        if c.fact.kind == "proposal"
    }
    for decision in DECISIONS:
        body = {
            "brief_digest": digest,
            "fact_id": proposals[decision.customer],
            "outcome": decision.outcome,
            "reason": decision.reason,
        }
        if decision.amendment:
            body["amendment"] = decision.amendment
        _expect_redirect(
            client.post(f"{run}/decide", data=body), f"the decision on {decision.customer}"
        )
    ids = {(customer_of_anchor(q.about.anchor), _place(q)): q.id for q in request.open_questions}
    for question in QUESTIONS:
        base = {"brief_digest": digest, "question_id": ids[(question.customer, question.place)]}
        if question.assumption is not None:
            body, route = {**base, "words": question.assumption}, "assume"
        else:
            body = {**base, "answer": question.answer or "", "reason": question.reason or ""}
            route = "answer"
        _expect_redirect(
            client.post(f"{run}/{route}", data=body),
            f"the handling of the question about {question.customer} ({question.place})",
        )
    _expect_redirect(
        client.post(f"{run}/sign", data={"brief_digest": digest, "outcome": "signed"}),
        "the sign-off",
    )
