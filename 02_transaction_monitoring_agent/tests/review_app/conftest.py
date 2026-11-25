"""Fixtures for the reviewer's application tests: a world over scripted models and a browser."""

import os
from collections.abc import Iterator

import pytest
from review_support import make_world

from fsi_common.app.testing import BrowserMissingError, launch_chromium


@pytest.fixture()
def world():
    """An application over a real run service on scripted models, with no run yet."""
    return make_world()


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
