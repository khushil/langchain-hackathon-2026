"""What the application's tests share: the real engine on the scripted reader, and clients."""

from __future__ import annotations

import re
import time

from kyc_fakes import ScriptedReader
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app
from fsi_common.app.session import SessionCodec
from fsi_common.records import Person
from review_app.context import Services
from review_app.drafts import DraftStore
from workflow.runs import KycRuns

TODAY = "2026-11-25"
DANA = Person(name="Dana Whitfield", role="Head of Compliance")
SAM = Person(name="Sam Okoye", role="Compliance Officer")
SECRET = b"test-secret"
BASE = "/kyc"
SMALL = ["CUST-001", "CUST-003", "CUST-016", "CUST-018"]
REQUEST_TEXT = "Review the proposed decisions on the applications"


def wait_for(runs: KycRuns, thread: str, wanted: str = "awaiting_review", seconds: float = 30.0):
    """Wait until a run reaches a status; fail with its error in words."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        status = runs.status(thread)
        if status == wanted:
            return thread
        if status == "failed":
            raise AssertionError(f"the run failed: {runs.error(thread)}")
        time.sleep(0.01)
    raise AssertionError(f"run {thread} is {runs.status(thread)}, not {wanted}")


def start_run(runs: KycRuns, customers: list[str] | None = None) -> str:
    """Start a run on the engine and wait for its review."""
    request = {"request": REQUEST_TEXT}
    if customers is not None:
        request["customer_ids"] = customers
    return wait_for(runs, runs.start(request))


def make_services(runs: KycRuns, **options) -> Services:
    """Make the services of the topic over a run service."""
    return Services(runs=lambda: runs, drafts=DraftStore(), today=lambda: TODAY, **options)


def make_client(
    runs: KycRuns, *, signed_in: Person | None = DANA, services: Services | None = None
) -> TestClient:
    """Make a test client for the application over a run service."""
    from review_app.plugin import build_plugin

    services = services or make_services(runs)
    app = create_app(AppConfig(secret=SECRET, topic_folders=()), topics=[build_plugin(services)])
    cookies = {}
    if signed_in is not None:
        cookies[app.state.cookie_name] = SessionCodec(SECRET).encode(signed_in)
    return TestClient(app, cookies=cookies, follow_redirects=False)


def switch_to(client: TestClient, person: Person) -> None:
    """Sign the client in as another person."""
    client.cookies.set(client.app.state.cookie_name, SessionCodec(SECRET).encode(person))


def text_of(html: str) -> str:
    """Return a page's text with the tags removed and white space folded."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def new_runs(**options) -> KycRuns:
    """A run service on the scripted reader."""
    return KycRuns(models=ScriptedReader(**options))


def settle_all(client: TestClient, runs: KycRuns, thread: str) -> None:
    """Accept every proposal and answer every question through the review routes, as Dana."""
    request = runs.review_request(thread)
    digest = request.brief_digest
    run = f"{BASE}/runs/{thread}"
    for statement in request.statements:
        for cited in statement.facts:
            if cited.fact.kind == "proposal":
                response = client.post(
                    f"{run}/decide",
                    data={
                        "brief_digest": digest,
                        "fact_id": cited.fact.id,
                        "outcome": "accept",
                        "reason": "Checked the application against the lists.",
                    },
                )
                assert response.status_code == 303, response.text
    for question in request.open_questions:
        response = client.post(
            f"{run}/answer",
            data={
                "brief_digest": digest,
                "question_id": question.id,
                "answer": "A different person.",
                "reason": "The application and the entry do not match.",
            },
        )
        assert response.status_code == 303, response.text
