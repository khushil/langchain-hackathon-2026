"""Fixtures for the application's browser tests: one Chromium and one served application."""

import os
from collections.abc import Iterator

import pytest
from browser_support import Served

from fsi_common.app.testing import BrowserMissingError, launch_chromium


@pytest.fixture(scope="module")
def browser() -> Iterator[object]:
    """One headless Chromium for the module; a failure when REQUIRE_BROWSER=1 and none starts."""
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


@pytest.fixture(scope="module")
def served() -> Iterator[Served]:
    """The application served on a free loopback port over the real engine, stopped afterwards."""
    server = Served()
    yield server
    server.stop()
