"""A real browser and the application served over the real engine, for the browser tests."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from kyc_fakes import ScriptedReader
from support import DANA, SECRET, SMALL, TODAY, make_client, settle_all, start_run, wait_for

from fsi_common.app import AppConfig, create_app
from fsi_common.app.browser_checks import RECORD_CLICKS
from fsi_common.app.session import SessionCodec
from fsi_common.app.testing import serve
from review_app.context import Services
from review_app.drafts import DraftStore
from review_app.plugin import build_plugin
from workflow.runs import KycRuns

SIZES = ((1366, 768), (390, 844))
SHOTS = os.environ.get("SHOTS_DIR")
BASE = "/kyc"


class Served:
    """The application served for a browser: a signed batch, a waiting, a stopped, a running."""

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.gate.set()
        self.reader = ScriptedReader(gate=self.gate)
        self.runs = KycRuns(models=self.reader)
        services = Services(runs=lambda: self.runs, drafts=DraftStore(), today=lambda: TODAY)
        self.app = create_app(
            AppConfig(secret=SECRET, topic_folders=()), topics=[build_plugin(services)]
        )
        client = make_client(self.runs, services=services)
        self.signed = start_run(self.runs, SMALL)
        settle_all(client, self.runs, self.signed)
        digest = self.runs.review_request(self.signed).brief_digest
        client.post(
            f"{BASE}/runs/{self.signed}/sign", data={"brief_digest": digest, "outcome": "signed"}
        )
        self.waiting = start_run(self.runs)
        self.reader.fail_for = ("CUST-004",)
        failed = self.runs.start({"request": "r", "customer_ids": ["CUST-004"]})
        self.failed = wait_for(self.runs, failed, "failed")
        self.reader.fail_for = ()
        self.gate.clear()
        self.running = self.runs.start({"request": "r", "customer_ids": ["CUST-001"]})
        self.server = serve(self.app)
        self.base_url = self.server.base_url

    def open(self, browser, size, *, signed_in: bool = True):
        """Open a page at a viewport size, signed in as the reviewer unless told otherwise."""
        context = browser.new_context(viewport={"width": size[0], "height": size[1]})
        context.add_init_script(RECORD_CLICKS)
        if signed_in:
            value = SessionCodec(SECRET).encode(DANA)
            context.add_cookies(
                [{"name": self.app.state.cookie_name, "value": value, "url": self.base_url}]
            )
        return context, context.new_page()

    def stop(self) -> None:
        """Let the held run finish, then stop the server by its own handle."""
        self.gate.set()
        self.server.stop()


def shot(page, name: str, size: tuple[int, int]) -> None:
    """Save a screenshot for a person when SHOTS_DIR is set."""
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"{name}-{size[0]}.png"))


PICTURE_FACTS = """() => {
  const matrix = document.querySelector('.matrix').getBoundingClientRect();
  return {rows: document.querySelectorAll('[data-hook=picture-row]').length,
          cells: document.querySelectorAll('[data-hook=picture-cell]').length,
          tiles: document.querySelectorAll('[data-hook=tile]').length,
          bottom: matrix.bottom, right: matrix.right,
          height: window.innerHeight, width: window.innerWidth};
}"""


def picture_problems(page, *, rows: int = 25, entries: int = 14) -> list[str]:
    """Check the picture holds every screening, fits its width and, on a wide screen, its height.

    Args:
        page: The Playwright page, loaded on a batch page.
        rows: The applications the batch holds.
        entries: The list entries each is set against.

    Returns:
        What is wrong, in words.
    """
    found = page.evaluate(PICTURE_FACTS)
    problems = []
    if (found["rows"], found["cells"]) != (rows, rows * entries):
        problems.append(f"The picture holds {found['rows']} rows and {found['cells']} cells.")
    if found["tiles"] != 3:
        problems.append(f"The page has {found['tiles']} tiles.")
    if found["right"] > found["width"]:
        problems.append("The picture runs past the right edge of the window.")
    if found["width"] >= 1100 and found["bottom"] > found["height"]:
        problems.append("The picture does not fit above the fold.")
    return problems
