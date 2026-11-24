"""Fixtures shared by the application's tests: a signed-in client over the fake run service."""

from __future__ import annotations

from review_fakes import FakeRuns
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app
from fsi_common.app.session import SessionCodec
from fsi_common.records import Person
from review_app.context import Services
from review_app.drafts import DraftStore
from review_app.plugin import build_plugin

TODAY = "2026-11-25"
DANA = Person(name="Dana Whitfield", role="Head of Compliance")


def make_client(runs: FakeRuns, *, signed_in: Person | None = DANA) -> TestClient:
    """Make a test client for the application over a fake run service."""
    services = Services(runs=lambda: runs, drafts=DraftStore(), today=lambda: TODAY)
    config = AppConfig(secret=b"test-secret", topic_folders=())
    app = create_app(config, topics=[build_plugin(services)])
    cookies = {}
    if signed_in is not None:
        cookies[app.state.cookie_name] = SessionCodec(b"test-secret").encode(signed_in)
    return TestClient(app, cookies=cookies, follow_redirects=False)
