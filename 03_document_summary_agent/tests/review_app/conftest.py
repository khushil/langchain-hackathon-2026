"""Fixtures for the reviewer's application tests: a fake run service and a signed-in client."""

import os
from collections.abc import Iterator

import pytest
from review_browser_support import Served, build_runs
from review_fakes import FakeRuns, examples_review, section_seven_review
from review_fixtures import make_client

from fsi_common.app.testing import BrowserMissingError, launch_chromium


@pytest.fixture()
def runs() -> FakeRuns:
    """A fake run service holding one run waiting for review, on the contract's examples."""
    fake = FakeRuns()
    fake.add("run-1", "awaiting_review", review=examples_review())
    return fake


@pytest.fixture()
def section7_runs() -> FakeRuns:
    """A fake run service holding one run waiting for review, on section 7."""
    fake = FakeRuns()
    fake.add("run-1", "awaiting_review", review=section_seven_review())
    return fake


@pytest.fixture()
def client(runs):
    """A client signed in as the reviewer."""
    return make_client(runs)


@pytest.fixture(scope="module")
def browser() -> Iterator[object]:
    """One headless Chromium for the worker; skipped, or a failure when REQUIRE_BROWSER=1."""
    sync_api = pytest.importorskip("playwright.sync_api", reason="Playwright is not installed")
    with sync_api.sync_playwright() as playwright:
        try:
            instance = launch_chromium(playwright)
        except BrowserMissingError as exc:
            if os.environ.get("REQUIRE_BROWSER") == "1":
                pytest.fail(str(exc))
            pytest.skip(str(exc))
        yield instance
        instance.close()


@pytest.fixture()
def served() -> Iterator[Served]:
    """The application served on a free loopback port over four runs, stopped afterwards."""
    server = Served(build_runs())
    yield server
    server.stop()
