"""The starting work of the compliance brief: one brief waiting for a reviewer and one signed.

Both briefs are runs of the real workflow on section 7 of PS26/4 for the first firm, answered
from the recorded model calls. The signed brief is taken through the application's own review
routes by a fictional reviewer, so every decision and the sign-off are built by the review route
from the wording in ``PROFILE`` (one decision on the firm profile) and ``DECISIONS`` (one for each
fact of the document) and nowhere else. Nothing here decides for anyone.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from starlette.testclient import TestClient

from fsi_common.app import AppConfig, SeedError, create_app
from fsi_common.app.offline import replay_only
from fsi_common.app.session import SessionCodec
from fsi_common.ids import digest_bytes, digest_json
from fsi_common.records import Person
from review_app.context import PREFIX, Services, runs_of
from utils.models import recordings_dir

DOCUMENT_ID = "PS26-4"
FIRM_ID = "FIRM-001"
SECTIONS = ("7",)
REVIEWER = Person(name="Dana Whitfield", role="Head of Compliance")
SEED_DATE = "2026-11-24"
"""The date on every seeded decision, fixed so that starting twice gives the same records."""
SECRET = b"starting-work"
SEED_NAME = "compliance-brief"
MARKER_FILE = "seeded.json"
"""The file a finished seed leaves in a state folder: the seed's name and what it was made from."""

WAIT_SECONDS = 180.0
POLL_SECONDS = 0.1


@dataclass(frozen=True)
class SeedDecision:
    """One decision of the fictional reviewer on one fact of the document, in her words.

    ``paragraph`` and ``quote`` say which fact ``fact_id`` is, so that a new recording that words
    a fact differently is reported by what changed and not only by an identifier.
    """

    fact_id: str
    paragraph: str
    quote: str
    outcome: str
    reason: str
    amendment: str | None = None


@dataclass(frozen=True)
class SeedProfile:
    """The reviewer's one decision on the firm profile, with the facts she was shown."""

    fact_ids: tuple[str, ...]
    outcome: str
    reason: str
    amendment: str | None = None


PROFILE = SeedProfile(
    fact_ids=(
        "fact:3ea55dfec196c112",
        "fact:5e3ea5fe0af13cf3",
        "fact:33cda8305e9f57c6",
        "fact:7678bf62b4d40a4b",
        "fact:8960216a3540d0ec",
        "fact:6493bf9915f4c712",
        "fact:0b7489f43a5963d5",
        "fact:98b11a93648d2406",
        "fact:7531942445b6e556",
        "fact:460ab6a8123c6350",
        "fact:a6dd7d8a6886b739",
        "fact:245c5a69de83b610",
    ),
    outcome="accept",
    reason=(
        "I read the profile against the firm table and the provider table. Harbour Mutual Bank, "
        "its type, customers and assets, both providers with their services and contract end "
        "dates, and the firm's own note on NimbusCloud all match the tables. The tables name no "
        "operational resilience senior manager, so the profile is right to say none is "
        "recorded; the firm has to fill that gap."
    ),
)
"""The firm profile as the recorded brief cites it, and the one decision on all of it."""

DECISIONS = (
    SeedDecision(
        "fact:be1caf14c1da80d4",
        "para:7.1",
        "Firms must submit an initial notification",
        "accept",
        "Paragraph 7.1 gives 4 hours from classifying the incident as major, and I read the "
        "quoted words in the paragraph itself.",
    ),
    SeedDecision(
        "fact:8dcce3936b557550",
        "para:7.1",
        "in any case no later than 24 hours",
        "accept",
        "Paragraph 7.1 also sets an outer limit of 24 hours after the incident is first "
        "detected, as quoted.",
    ),
    SeedDecision(
        "fact:98b628305fb9d4a4",
        "para:7.2",
        "Firms must submit an intermediate report",
        "accept",
        "Paragraph 7.2 gives 72 hours from the initial notification, as quoted.",
    ),
    SeedDecision(
        "fact:80507750f54be85e",
        "para:7.3",
        "Firms must submit a final report",
        "accept",
        "Paragraph 7.3 gives 30 business days from the incident being resolved, as quoted.",
    ),
    SeedDecision(
        "fact:ad8c659e73a33138",
        "para:7.3",
        "The final report must include",
        "accept",
        "Paragraph 7.3 also asks for a root-cause analysis and the lessons learned in the "
        "final report.",
    ),
    SeedDecision(
        "fact:5f2e1907bf090f40",
        "para:7.4",
        "the firm remains responsible for reporting it",
        "accept",
        "Paragraph 7.4 leaves the reporting with the firm when a third-party provider causes the "
        "incident. I read the whole sentence, not only the quoted words.",
    ),
)
"""The reviewer's decision on each fact of the document the recorded brief cites."""


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
        f"The state folder {folder} holds briefs that this start did not make from these "
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
    if problems:
        raise SeedError(
            "The recorded brief is not the one the seed's decisions were written for. "
            + ". ".join(problems)
            + "."
        )
    if request.open_questions:
        raise SeedError("The recorded brief has open questions, which the seed does not answer.")


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
