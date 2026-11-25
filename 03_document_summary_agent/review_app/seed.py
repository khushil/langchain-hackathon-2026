"""The starting work of the compliance brief: one brief waiting for a reviewer and one signed.

Both briefs are runs of the real workflow on all ten sections of PS26/4 for the first firm,
answered from the recorded model calls. The signed brief is taken through the application's own
review routes by a fictional reviewer, so every decision, answer, accepted assumption and the
sign-off are built by the review route from the wording in ``PROFILE`` (one decision on the firm
profile), ``DECISIONS`` (one for each fact of the document) and ``QUESTIONS`` (one for each open
question) and nowhere else. Nothing here decides for anyone.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, replace
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, SeedError, create_app
from fsi_common.app.offline import replay_only
from fsi_common.app.session import SessionCodec
from fsi_common.ids import digest_bytes, digest_json
from fsi_common.records import Person
from review_app.context import PREFIX, Services, runs_of
from review_app.seed_fixture import (
    DECISIONS,
    PROFILE,
    QUESTIONS,
)
from utils.models import recordings_dir

DOCUMENT_ID = "PS26-4"
FIRM_ID = "FIRM-001"
SECTIONS = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10")
REVIEWER = Person(name="Dana Whitfield", role="Head of Compliance")
SEED_DATE = "2026-11-24"
"""The date on every seeded decision, fixed so that starting twice gives the same records."""
SECRET = b"starting-work"
SEED_NAME = "compliance-brief"
MARKER_FILE = "seeded.json"
"""The file a finished seed leaves in a state folder: the seed's name and what it was made from."""

WAIT_SECONDS = 180.0
POLL_SECONDS = 0.1


class _FailureCatcher(logging.Handler):
    """Keeps the exceptions the run service logs when a run fails, so the cause can be named."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.caught: list[BaseException] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.exc_info and record.exc_info[1] is not None:
            self.caught.append(record.exc_info[1])


def seed_compliance_brief(services: Services) -> None:
    """Make a brief that waits for a reviewer and a brief that is signed.

    When the services keep their state in a folder, a finished seed leaves a marker there, and a
    later start that finds the marker matching leaves the briefs as they are, so a restart adds no
    second copy. A folder that holds briefs with no marker, or a marker made from other recordings
    or another fixture, is refused: serving it would show a seed that failed partway or one made
    from an older recording.

    The runs are made from the recorded model calls whatever the model settings are, and the
    settings are put back afterwards, so a brief a user starts later runs as configured. The
    waiting brief is made first: the engine carries a signed brief's decisions into later runs of
    the same firm and document, so a brief made after the signed one would arrive already decided
    and leave the reviewer nothing to do.

    Args:
        services: The run service, library and held decisions of the topic being served.

    Raises:
        ReplayMissError: If a model call of the run has no recording; its message names the hash.
        SeedError: If a run stops for another reason, the fixture does not match the facts the
            brief cites, the review route refuses a decision or the sign-off, the state folder
            holds briefs this seed did not make from these recordings, or the marker cannot be
            written.
    """
    from review_app.plugin import build_plugin  # the plug-in imports this module for its seed

    if _already_seeded(services):
        return
    shadow = replace(services, today=lambda: SEED_DATE)
    app = create_app(AppConfig(secret=SECRET, topic_folders=()), topics=[build_plugin(shadow)])
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(app.state.cookie_name, SessionCodec(SECRET).encode(REVIEWER))
    catcher = _FailureCatcher()
    log = logging.getLogger("workflow.runs")
    log.addHandler(catcher)
    try:
        with replay_only():
            _start_and_wait(client, services, catcher)
            signed = _start_and_wait(client, services, catcher)
            _review_and_sign(client, services, signed)
    finally:
        log.removeHandler(catcher)
    _write_marker(services)


def seed_identity() -> str:
    """Return what the seed is made from: its fixture and every recorded model call.

    Returns:
        A digest that changes when a decision, the profile, the document, the firm, the sections
        or any file of the recordings folder changes.
    """
    folder = recordings_dir(os.environ)
    recordings = {p.name: digest_bytes(p.read_bytes()) for p in sorted(folder.glob("*.json"))}
    return digest_json(
        {
            "fixture": [DOCUMENT_ID, FIRM_ID, list(SECTIONS), SEED_DATE],
            "profile": asdict(PROFILE),
            "decisions": [asdict(d) for d in DECISIONS],
            "questions": [asdict(q) for q in QUESTIONS],
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
    raise SeedError(_refusal(services, Path(folder)))


def fresh_folder(folder: Path) -> Path:
    """Name a state folder that does not exist yet, beside one that does.

    Args:
        folder: The folder that is kept as it is.

    Returns:
        The sibling ``<name>-2``, or the first of ``-3``, ``-4`` and so on that is free.
    """
    number = 2
    while (candidate := folder.with_name(f"{folder.name}-{number}")).exists():
        number += 1
    return candidate


def _holds(services: Services) -> str:
    """Say what the services' runs hold, in words: how many briefs and how many are signed."""
    try:
        runs = runs_of(services)
        statuses = [runs.status(t) for t in runs.list_runs()]
    except HTTPException:  # the engine is not part of this build, so the folder cannot be read
        return "state that this start cannot read"
    count = len(statuses)
    if count == 0:
        return "no brief, with a seed that stopped partway"
    signed = sum(s == "signed" for s in statuses)
    return f"{count} brief{'' if count == 1 else 's'}, {signed} of them signed"


def _refusal(services: Services, folder: Path) -> str:
    """Write the refusal of a folder the seed did not make: what it holds and a fresh folder.

    The words never advise a delete or a move, because the folder may hold a signed brief.
    """
    command = f"APP_STATE_DIR={fresh_folder(folder)} APP_SEED={SEED_NAME} make serve"
    return (
        f"The state folder {folder} holds {_holds(services)}, which this start did not make from "
        "these recordings, or a seed that stopped partway. Nothing in it is changed. To start "
        f"with a fresh folder and keep this one as it is, run `{command}`."
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


def _start_and_wait(client: TestClient, services: Services, catcher: _FailureCatcher) -> str:
    """Start a brief through the start route and wait until it stops at the review."""
    form = {"document_id": DOCUMENT_ID, "firm_id": FIRM_ID, "sections": list(SECTIONS)}
    started = client.post(f"{PREFIX}/runs", data=form)
    if started.status_code != 303:
        raise SeedError(
            f"The start route answered {started.status_code} instead of starting a brief."
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
    raise SeedError(f"The brief did not reach its review within {WAIT_SECONDS:g} seconds.")


def _failure(catcher: _FailureCatcher, reason: str | None) -> BaseException:
    """Return what stopped the run: a missing recording as itself, else a summary in words."""
    from fsi_common.model import ReplayMissError

    for caught in catcher.caught:
        link: BaseException | None = caught
        while link is not None:
            if isinstance(link, ReplayMissError):
                return link
            link = link.__cause__ or link.__context__
    return SeedError(
        f"The brief stopped before its review: {reason or 'the engine gave no reason'}."
    )


def _words_of(cited) -> str:
    """Name a fact the brief cites by its paragraph and the start of its quote."""
    fact = cited.fact
    return f'{fact.id} ({fact.subject.anchor}, "{fact.quote[:60]}")'


def _question_problems(questions) -> list[str]:
    """Say which open questions of the brief the seed has no answer for, and the reverse."""
    anchors = [q.about.anchor for q in questions]
    wanted = {q.paragraph for q in QUESTIONS}
    new = [
        f'{q.about.anchor} ("{q.question[:60]}")' for q in questions if q.about.anchor not in wanted
    ]
    gone = sorted(wanted - set(anchors))
    problems = []
    if len(set(anchors)) != len(anchors):
        problems.append("the brief has two open questions about one paragraph")
    if new:
        problems.append(f"open questions on the brief with no answer in the seed: {'; '.join(new)}")
    if gone:
        problems.append(f"open questions in the seed that are not on the brief: {', '.join(gone)}")
    return problems


def _check_fixture(request) -> None:
    """Refuse a recorded brief the fixture was not written for, naming each fact that changed."""
    from review_app.profile import is_profile

    cited = {}
    for statement in request.statements:
        for fact in statement.facts:
            cited.setdefault(fact.fact.id, fact)
    profile = {i: c for i, c in cited.items() if is_profile(c.fact)}
    document = {i: c for i, c in cited.items() if not is_profile(c.fact)}
    problems = []
    for label, found, wanted in (
        ("firm profile", profile, set(PROFILE.fact_ids)),
        ("document", document, {d.fact_id for d in DECISIONS}),
    ):
        new = [_words_of(c) for i, c in found.items() if i not in wanted]
        gone = sorted(wanted - set(found))
        if new:
            problems.append(
                f"{label} facts on the brief with no decision in the seed: {'; '.join(new)}"
            )
        if gone:
            problems.append(
                f"{label} facts in the seed that are not on the brief: {', '.join(gone)}"
            )
    problems += _question_problems(request.open_questions)
    if problems:
        raise SeedError(
            "The recorded brief is not the one the seed's decisions were written for. "
            + ". ".join(problems)
            + "."
        )


def _review_and_sign(client: TestClient, services: Services, thread: str) -> None:
    """Record the fixture's decisions through the review routes, then sign through them."""
    request = runs_of(services).review_request(thread)
    _check_fixture(request)
    run = f"{PREFIX}/runs/{thread}"
    digest = request.brief_digest
    body = {"brief_digest": digest, "outcome": PROFILE.outcome, "reason": PROFILE.reason}
    if PROFILE.amendment:
        body["amendment"] = PROFILE.amendment
    _expect_redirect(client.post(f"{run}/profile", data=body), "the decision on the firm profile")
    for decision in DECISIONS:
        body = {
            "brief_digest": digest,
            "fact_id": decision.fact_id,
            "outcome": decision.outcome,
            "reason": decision.reason,
        }
        if decision.amendment:
            body["amendment"] = decision.amendment
        _expect_redirect(
            client.post(f"{run}/decide", data=body), f"the decision on {decision.fact_id}"
        )
    ids = {q.about.anchor: q.id for q in request.open_questions}
    for question in QUESTIONS:
        if question.assumption is not None:
            body = {
                "brief_digest": digest,
                "question_id": ids[question.paragraph],
                "words": question.assumption,
            }
            _expect_redirect(
                client.post(f"{run}/assume", data=body),
                f"the assumption for the question about {question.paragraph}",
            )
        else:
            body = {
                "brief_digest": digest,
                "question_id": ids[question.paragraph],
                "answer": question.answer or "",
                "reason": question.reason or "",
            }
            _expect_redirect(
                client.post(f"{run}/answer", data=body),
                f"the answer to the question about {question.paragraph}",
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
