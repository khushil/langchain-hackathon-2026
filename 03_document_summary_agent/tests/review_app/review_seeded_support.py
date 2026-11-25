"""The seeded compliance brief, served for page and browser tests on the recordings."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from html import unescape

from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app
from fsi_common.app.browser_checks import RECORD_CLICKS
from fsi_common.app.offline import replay_only
from fsi_common.app.session import SessionCodec
from fsi_common.app.testing import RunningServer, serve
from fsi_common.records import Person
from review_app.context import PREFIX, Services
from review_app.plugin import build_plugin
from review_app.seed import REVIEWER, seed_compliance_brief
from workflow.runs import BriefRuns

TODAY = "2026-11-25"
SECRET = b"seeded-secret"
ALL_SECTIONS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]


def text_of(html: str) -> str:
    """Return a page's text with the tags removed and the white space folded."""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html)))


@dataclass
class Seeded:
    """The seeded run service, its services and an application over them."""

    runs: BriefRuns
    services: Services
    app: object
    running: RunningServer | None = None

    def thread(self, status: str) -> str:
        """Return the thread of the first run in a status."""
        return next(t for t in self.runs.list_runs() if self.runs.status(t) == status)

    @property
    def waiting(self) -> str:
        """The brief waiting for a reviewer."""
        return self.thread("awaiting_review")

    @property
    def signed(self) -> str:
        """The signed brief."""
        return self.thread("signed")

    def client(self, person: Person | None = REVIEWER) -> TestClient:
        """Return a client, signed in as a person unless it is told nobody."""
        cookies = {}
        if person is not None:
            cookies[self.app.state.cookie_name] = SessionCodec(SECRET).encode(person)
        return TestClient(self.app, cookies=cookies, follow_redirects=False)

    def serve(self) -> str:
        """Serve the application on a loopback port and return its address."""
        self.running = serve(self.app)
        return self.running.base_url

    def open(self, browser, size, *, signed_in: bool = True):
        """Open a page at a viewport size, signed in as the seeded reviewer unless told not."""
        base = self.running.base_url if self.running else self.serve()
        context = browser.new_context(viewport={"width": size[0], "height": size[1]})
        context.add_init_script(RECORD_CLICKS)
        if signed_in:
            value = SessionCodec(SECRET).encode(REVIEWER)
            context.add_cookies([{"name": self.app.state.cookie_name, "value": value, "url": base}])
        return context, context.new_page()

    def stop(self) -> None:
        """Stop the server by its own handle."""
        if self.running:
            self.running.stop()
            self.running = None

    def start_another(self) -> str:
        """Start a brief on every section through the start route; wait for its review."""
        client = self.client()
        with replay_only():
            reply = client.post(
                f"{PREFIX}/runs",
                data={"document_id": "PS26-4", "firm_id": "FIRM-001", "sections": ALL_SECTIONS},
            )
            assert reply.status_code == 303, reply.status_code
            thread = reply.headers["location"].rsplit("/", 1)[1]
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if self.runs.status(thread) != "running":
                    break
                time.sleep(0.1)
        assert self.runs.status(thread) == "awaiting_review", self.runs.error(thread)
        return thread


def make_seeded() -> Seeded:
    """Seed one brief waiting and one signed, as the application does at its start."""
    with replay_only():
        runs = BriefRuns()
    services = Services(runs=lambda: runs, today=lambda: TODAY)
    seed_compliance_brief(services)
    app = create_app(AppConfig(secret=SECRET, topic_folders=()), topics=[build_plugin(services)])
    return Seeded(runs, services, app)
