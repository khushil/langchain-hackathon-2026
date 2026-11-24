"""Fixtures for the shell's tests: one real browser for each worker."""

import os
from collections.abc import Iterator

import pytest

from fsi_common.app.testing import BrowserMissingError, launch_chromium


@pytest.fixture(scope="module")
def browser() -> Iterator[object]:
    """One headless Chromium for the module, closed before any other module's tests run.

    Playwright keeps an event loop running while it is open, which would stop other tests that
    start their own. The tests are skipped, or fail when REQUIRE_BROWSER=1, if none can start.
    """
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
