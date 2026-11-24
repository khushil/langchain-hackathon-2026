"""The starting work of the compliance brief: one brief waiting for a reviewer and one signed.

Both briefs are runs of the real workflow on section 7 of PS26/4 for the first firm, answered
from the recorded model calls. The signed brief is taken through the application's own review
routes by a fictional reviewer, so every decision and the sign-off are built by the review route
from the wording in ``DECISIONS`` and nowhere else. Nothing here decides for anyone.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, replace

from starlette.testclient import TestClient

from fsi_common.app import AppConfig, SeedError, create_app
from fsi_common.app.offline import replay_only
from fsi_common.app.session import SessionCodec
from fsi_common.records import Person
from review_app.context import PREFIX, Services, runs_of

DOCUMENT_ID = "PS26-4"
FIRM_ID = "FIRM-001"
SECTIONS = ("7",)
REVIEWER = Person(name="Dana Whitfield", role="Head of Compliance")
SEED_DATE = "2026-11-24"
"""The date on every seeded decision, fixed so that starting twice gives the same records."""
SECRET = b"starting-work"
WAIT_SECONDS = 180.0
POLL_SECONDS = 0.1


@dataclass(frozen=True)
class SeedDecision:
    """One decision of the fictional reviewer on one fact, in the reviewer's words."""

    fact_id: str
    outcome: str
    reason: str
    amendment: str | None = None


DECISIONS = (
    SeedDecision(
        "fact:3ea55dfec196c112",
        "accept",
        "The firm table gives the name as Harbour Mutual Bank, the firm this brief is for.",
    ),
    SeedDecision(
        "fact:5e3ea5fe0af13cf3", "accept", "The firm table gives the type as a retail bank."
    ),
    SeedDecision("fact:33cda8305e9f57c6", "accept", "The firm table gives 1,200,000 customers."),
    SeedDecision(
        "fact:7678bf62b4d40a4b", "accept", "The firm table gives total assets of £9 billion."
    ),
    SeedDecision(
        "fact:8960216a3540d0ec",
        "accept",
        "The firm table names no operational resilience senior manager, so the brief is right "
        "to say none is recorded. The firm has to fill that gap.",
    ),
    SeedDecision(
        "fact:98b11a93648d2406",
        "accept",
        "The firm table links the first provider as material, with a contract ending on "
        "30 June 2027.",
    ),
    SeedDecision(
        "fact:6493bf9915f4c712",
        "accept",
        "The provider table names the first provider NimbusCloud.",
    ),
    SeedDecision(
        "fact:0b7489f43a5963d5",
        "accept",
        "The provider table gives its service as core banking hosting.",
    ),
    SeedDecision(
        "fact:a6dd7d8a6886b739",
        "accept",
        "The firm table links the second provider as material, with a contract ending on "
        "31 December 2029.",
    ),
    SeedDecision(
        "fact:7531942445b6e556",
        "accept",
        "The provider table names the second provider PayCore Ltd.",
    ),
    SeedDecision(
        "fact:460ab6a8123c6350",
        "accept",
        "The provider table gives its service as card processing.",
    ),
    SeedDecision(
        "fact:245c5a69de83b610",
        "accept",
        "The firm's own note says mobile banking and card payments both run on NimbusCloud. I "
        "have taken it as the firm states it.",
    ),
    SeedDecision(
        "fact:7d0607968a1b5c72",
        "accept",
        "Paragraph 7.1 gives 4 hours from classifying the incident as major, and I read the "
        "quoted words in the paragraph itself.",
    ),
    SeedDecision(
        "fact:98b628305fb9d4a4",
        "accept",
        "Paragraph 7.2 gives 72 hours from the initial notification, as quoted.",
    ),
    SeedDecision(
        "fact:80507750f54be85e",
        "accept",
        "Paragraph 7.3 gives 30 business days from the incident being resolved, as quoted.",
    ),
    SeedDecision(
        "fact:ad8c659e73a33138",
        "accept",
        "Paragraph 7.3 also asks for a root-cause analysis and the lessons learned in the "
        "final report.",
    ),
)
"""The reviewer's decision on each fact the recorded brief cites, written once as fixture data."""


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

    The runs are made from the recorded model calls whatever the model settings are, and the
    settings are put back afterwards, so a brief a user starts later runs as configured. The
    waiting brief is made first: the engine carries a signed brief's decisions into later runs of
    the same firm and document, so a brief made after the signed one would arrive already decided
    and leave the reviewer nothing to do. The run service in ``services`` must be empty; each call
    adds two runs to it.

    Args:
        services: The run service, library and held decisions of the topic being served.

    Raises:
        ReplayMissError: If a model call of the run has no recording; its message names the hash.
        SeedError: If a run stops for another reason, the fixture does not match the facts the
            brief cites, or the review route refuses a decision or the sign-off.
    """
    from review_app.plugin import build_plugin  # the plug-in imports this module for its seed

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


def _review_and_sign(client: TestClient, services: Services, thread: str) -> None:
    """Record the fixture's decisions through the review route, then sign through it."""
    request = runs_of(services).review_request(thread)
    cited = {c.fact.id for s in request.statements for c in s.facts}
    wanted = [d.fact_id for d in DECISIONS]
    missing = sorted(cited - set(wanted))
    stray = sorted(set(wanted) - cited)
    if missing or stray:
        raise SeedError(
            "The seed's decisions do not match the facts the recorded brief cites: "
            f"no decision for {', '.join(missing) or 'none'}; "
            f"decisions on facts not on the brief: {', '.join(stray) or 'none'}."
        )
    if request.open_questions:
        raise SeedError("The recorded brief has open questions, which the seed does not answer.")
    run = f"{PREFIX}/runs/{thread}"
    for decision in DECISIONS:
        body = {
            "brief_digest": request.brief_digest,
            "fact_id": decision.fact_id,
            "outcome": decision.outcome,
            "reason": decision.reason,
        }
        if decision.amendment:
            body["amendment"] = decision.amendment
        _expect_redirect(
            client.post(f"{run}/decide", data=body), f"the decision on {decision.fact_id}"
        )
    sign = {"brief_digest": request.brief_digest, "outcome": "signed"}
    _expect_redirect(client.post(f"{run}/sign", data=sign), "the sign-off")


def _expect_redirect(response, what: str) -> None:
    if response.status_code != 303:
        problem = re.search(r'data-hook="form-problem">(.*?)</p>', response.text, re.S)
        words = " ".join(re.sub(r"<[^>]+>", " ", problem.group(1)).split()) if problem else ""
        raise SeedError(
            f"The review route refused {what} with {response.status_code}: "
            f"{words or 'no reason given on the page'}"
        )
