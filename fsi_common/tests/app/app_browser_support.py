"""A real browser for the shell's tests: one Chromium per worker, one page per test."""

from __future__ import annotations

import os
from pathlib import Path

from fsi_common.app.browser_checks import RECORD_CLICKS

SIZES = ((1366, 768), (1920, 1080))
SHOTS = os.environ.get("SHOTS_DIR")


def open_page(browser, base_url: str, size: tuple[int, int], *, cookies=None):
    """Open a page of the application at a viewport size, recording click listeners."""
    context = browser.new_context(viewport={"width": size[0], "height": size[1]})
    context.add_init_script(RECORD_CLICKS)
    if cookies:
        context.add_cookies([{**c, "url": base_url} for c in cookies])
    return context, context.new_page()


def shot(page, name: str, size: tuple[int, int]) -> None:
    """Save a screenshot for a person when SHOTS_DIR is set."""
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"{name}-{size[0]}.png"))
