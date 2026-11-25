"""A served application over the real run service on scripted models, and what tests do on it."""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass

from engine_fakes import ScriptedModels
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app
from fsi_common.app.session import SessionCodec
from fsi_common.records import Person
from review_app.context import PREFIX, Services
from review_app.drafts import DraftStore
from review_app.plugin import build_plugin
from workflow.runs import MonitorRuns

TODAY = "2026-11-25"
SECRET = b"test-secret"
DANA = Person(name="Dana Whitfield", role="Head of Compliance")
SAM = Person(name="Sam Okafor", role="Fraud Analyst")
WINDOW = {"end": "2026-10-19"}


@dataclass
class World:
    """The run service, the services over it and the application built on them."""

    runs: MonitorRuns
    services: Services
    app: object

    def client(self, person: Person | None = DANA) -> TestClient:
        """Make a client signed in as a person, or as nobody; it does not follow redirects."""
        cookies = {}
        if person is not None:
            cookies[self.app.state.cookie_name] = SessionCodec(SECRET).encode(person)
        return TestClient(self.app, cookies=cookies, follow_redirects=False)


def make_world(models: ScriptedModels | None = None, *, state_dir=None) -> World:
    """Build an application over a real run service answered by scripted models."""
    runs = MonitorRuns(models=models or ScriptedModels(), state_dir=state_dir)
    services = Services(runs=lambda: runs, drafts=DraftStore(), today=lambda: TODAY)
    app = create_app(AppConfig(secret=SECRET, topic_folders=()), topics=[build_plugin(services)])
    return World(runs, services, app)


def text(response) -> str:
    """The words of a page: tags taken out, entities read, white space made one space."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", response.text)).split())


def marks(page, state: str) -> int:
    """Count the marks of the picture that stand in one state."""
    return page.text.count(f'data-hook="mark" data-state="{state}"')


def wait_for(runs: MonitorRuns, thread: str, wanted: set[str], timeout: float = 30.0) -> str:
    """Poll a run until its status is one of ``wanted``."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        status = runs.status(thread)
        if status in wanted:
            return status
        time.sleep(0.01)
    raise AssertionError(f"run {thread} is {runs.status(thread)}, not {wanted}")


def start_run(world: World, user: str = "USR-001", **window: str) -> str:
    """Start a run through the start route and wait until it waits for a reviewer."""
    client = world.client()
    response = client.post(f"{PREFIX}/runs", data={"user_id": user, **window})
    assert response.status_code == 303, response.text[:300]
    thread = response.headers["location"].rsplit("/", 1)[1]
    wait_for(world.runs, thread, {"awaiting_review"})
    return thread


def run_path(thread: str, *parts: str) -> str:
    """Return the address of a page of a run."""
    return "/".join([PREFIX, "runs", thread, *parts])


def record_all(world: World, thread: str, *, client: TestClient | None = None, **form) -> None:
    """Decide every assessment of a run through the review route: agree, with a reason."""
    client = client or world.client()
    request = world.runs.review_request(thread)
    for cited in request.assessments:
        body = {
            "brief_digest": request.brief_digest,
            "fact_id": cited.fact.id,
            "outcome": "accept",
            "reason": "Checked against what the customer told us.",
            **form,
        }
        response = client.post(run_path(thread, "decide"), data=body)
        assert response.status_code == 303, response.text[:300]
