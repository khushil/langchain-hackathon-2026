"""The starting work of transaction monitoring: one run signed and one run waiting for a reviewer.

Both runs are runs of the real workflow on the first customer's stream, answered from the
recorded model calls. The signed run reads the six transactions before 19 October and is taken
through the application's own review routes by a fictional reviewer, so every decision and the
sign-off are built by the review route from the wording in ``DECISIONS`` and nowhere else. The
waiting run reads the whole stream: the engine carries the signed run's decisions into it, so its
first six transactions arrive decided and the four of the later week wait for a person. Nothing
here decides for anyone.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path

from starlette.testclient import TestClient

from fsi_common.app import AppConfig, SeedError, TopicPlugin, create_app
from fsi_common.app.offline import replay_only
from fsi_common.app.session import SessionCodec
from fsi_common.ids import digest_bytes, digest_json
from fsi_common.records import Person
from review_app.context import PREFIX, Services, runs_of
from review_app.seed_fixture import DECISIONS, USER_ID, WINDOW_END
from utils.models import recordings_dir
from utils.review import ReviewRequest

REVIEWER = Person(name="Dana Whitfield", role="Head of Compliance")
SEED_DATE = "2026-11-25"
"""The date on every seeded decision, fixed so that starting twice gives the same records."""
SECRET = b"starting-work"
SEED_NAME = "transaction-monitoring"
MARKER_FILE = "seeded.json"
"""The file a finished seed leaves in a state folder: the seed's name and what it was made from."""

WAIT_SECONDS = 300.0
POLL_SECONDS = 0.1


class _FailureCatcher(logging.Handler):
    """Keeps the exceptions the run service logs when a run fails, so the cause can be named."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.caught: list[BaseException] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.exc_info and record.exc_info[1] is not None:
            self.caught.append(record.exc_info[1])


def seed_transaction_monitoring(
    services: Services, build: Callable[[Services], TopicPlugin]
) -> None:
    """Make a run that is signed and a run that waits for a reviewer.

    When the services keep their state in a folder, a finished seed leaves a marker there, and a
    later start that finds the marker matching leaves the runs as they are, so a restart adds no
    second copy. A folder that holds runs with no marker, or a marker made from other recordings
    or another fixture, is refused: serving it would show a seed that failed partway or one made
    from an older recording.

    The runs are made from the recorded model calls whatever the model settings are, and the
    settings are put back afterwards. The signed run is made first, because the engine carries a
    signed run's decisions into later runs on the same customer, and the waiting run is the one
    that shows them carried.

    Args:
        services: The run service and held decisions of the topic being served.
        build: Makes the topic's plug-in over a set of services, for the seed's own application.

    Raises:
        ReplayMissError: If a model call of a run has no recording; its message names the hash.
        SeedError: If a run stops for another reason, the fixture does not match the proposals
            the run holds, the review route refuses a decision or the sign-off, the state folder
            holds runs this seed did not make from these recordings, or the marker cannot be
            written.
    """
    if _already_seeded(services):
        return
    shadow = replace(services, today=lambda: SEED_DATE)
    app = create_app(AppConfig(secret=SECRET, topic_folders=()), topics=[build(shadow)])
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(app.state.cookie_name, SessionCodec(SECRET).encode(REVIEWER))
    catcher = _FailureCatcher()
    log = logging.getLogger("workflow.runs")
    log.addHandler(catcher)
    try:
        with replay_only():
            signed = _start_and_wait(client, services, catcher, {"end": WINDOW_END})
            _review_and_sign(client, services, signed)
            _start_and_wait(client, services, catcher, {})
    finally:
        log.removeHandler(catcher)
    _write_marker(services)


def seed_identity() -> str:
    """Return what the seed is made from: its fixture and every recorded model call.

    Returns:
        A digest that changes when a decision, the customer, the window or any file of the
        recordings folder changes.
    """
    folder = recordings_dir(os.environ)
    recordings = {p.name: digest_bytes(p.read_bytes()) for p in sorted(folder.glob("*.json"))}
    return digest_json(
        {
            "fixture": [USER_ID, WINDOW_END, SEED_DATE],
            "decisions": [asdict(d) for d in DECISIONS],
            "recordings": recordings,
        }
    )


def _already_seeded(services: Services) -> bool:
    """Say whether this state folder was seeded from these recordings; refuse one that was not."""
    folder = services.state_dir
    if folder is None:
        return False
    marker = folder / MARKER_FILE
    if not marker.exists() and not runs_of(services).list_runs():
        return False
    try:
        held = json.loads(marker.read_text())
    except (OSError, ValueError):
        held = None
    if held == {"seed": SEED_NAME, "digest": seed_identity()}:
        return True
    raise SeedError(
        f"The state folder {folder} holds runs that this start did not make from these "
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


def _start_and_wait(
    client: TestClient, services: Services, catcher: _FailureCatcher, window: dict[str, str]
) -> str:
    """Start a run through the start route and wait until it stops at the review."""
    started = client.post(f"{PREFIX}/runs", data={"user_id": USER_ID, **window})
    if started.status_code != 303:
        raise SeedError(
            f"The start route answered {started.status_code} instead of starting a run."
        )
    thread = started.headers["location"].rsplit("/", 1)[1]
    runs = runs_of(services)
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        status = runs.status(thread)
        if status == "awaiting_review":
            return thread
        if status != "running":
            raise _failure(catcher, runs.error(thread))
        time.sleep(POLL_SECONDS)
    raise SeedError(f"The run did not reach its review within {WAIT_SECONDS:g} seconds.")


def _failure(catcher: _FailureCatcher, reason: str | None) -> BaseException:
    """Return what stopped the run: a missing recording as itself, else a summary in words."""
    from fsi_common.model import ReplayMissError

    for caught in catcher.caught:
        link: BaseException | None = caught
        while link is not None:
            if isinstance(link, ReplayMissError):
                return link
            link = link.__cause__ or link.__context__
    return SeedError(f"The run stopped before its review: {reason or 'the engine gave no reason'}.")


def _check_fixture(request: ReviewRequest) -> None:
    """Refuse a recorded run the fixture was not written for, naming each transaction that moved."""
    held = {c.fact.subject.anchor.partition(":")[2]: c for c in request.assessments}
    wanted = {d.tx_id: d for d in DECISIONS}
    problems = []
    for tx_id in sorted(set(held) - set(wanted)):
        problems.append(f"{tx_id} is on the brief and has no decision in the seed")
    for tx_id in sorted(set(wanted) - set(held)):
        problems.append(f"{tx_id} has a decision in the seed and is not on the brief")
    for tx_id in sorted(set(held) & set(wanted)):
        proposed = held[tx_id].fact.attributes["proposed_decision"]
        if proposed != wanted[tx_id].proposal:
            problems.append(
                f"{tx_id} was proposed as {proposed} and the seed was written for "
                f"{wanted[tx_id].proposal}"
            )
    if request.open_questions:
        problems.append(
            f"{len(request.open_questions)} open question(s) have no answer in the seed"
        )
    if problems:
        raise SeedError(
            "The recorded run is not the one the seed's decisions were written for. "
            + "; ".join(problems)
            + "."
        )


def _review_and_sign(client: TestClient, services: Services, thread: str) -> None:
    """Record the fixture's decisions through the review routes, then sign through them."""
    request = runs_of(services).review_request(thread)
    _check_fixture(request)
    ids = {c.fact.subject.anchor.partition(":")[2]: c.fact.id for c in request.assessments}
    run = f"{PREFIX}/runs/{thread}"
    digest = request.brief_digest
    for decision in DECISIONS:
        body = {
            "brief_digest": digest,
            "fact_id": ids[decision.tx_id],
            "outcome": decision.outcome,
            "reason": decision.reason,
        }
        if decision.final:
            body["final"] = decision.final
        if decision.wording:
            body["wording"] = decision.wording
        _expect_redirect(
            client.post(f"{run}/decide", data=body), f"the decision on {decision.tx_id}"
        )
    sign = {"brief_digest": digest, "outcome": "signed"}
    _expect_redirect(client.post(f"{run}/sign", data=sign), "the sign-off")


def _expect_redirect(response, what: str) -> None:
    if response.status_code != 303:
        problem = re.search(r'data-hook="form-problem">(.*?)</p>', response.text, re.S)
        words = " ".join(re.sub(r"<[^>]+>", " ", problem.group(1)).split()) if problem else ""
        raise SeedError(
            f"The review route refused {what} with {response.status_code}: "
            f"{words or 'no reason given on the page'}"
        )
