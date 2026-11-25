"""A real browser and a served application for the transaction monitoring pages' browser tests."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from engine_fakes import ScriptedModels
from review_support import (
    DANA,
    SECRET,
    WINDOW,
    World,
    make_world,
    record_all,
    run_path,
    start_run,
    wait_for,
)

from fsi_common.app.browser_checks import RECORD_CLICKS
from fsi_common.app.session import SessionCodec
from fsi_common.app.testing import serve
from review_app.context import PREFIX

SIZES = ((1366, 768), (390, 844))
SHOTS = os.environ.get("SHOTS_DIR")


class Served:
    """The application served for a browser over four runs: failed, signed, waiting and running."""

    def __init__(self) -> None:
        self.models = ScriptedModels()
        self.world: World = make_world(self.models)
        runs = self.world.runs
        client = self.world.client()
        self.models.fail = ("TX-1003",)
        failed = client.post(f"{PREFIX}/runs", data={"user_id": "USR-001", **WINDOW})
        self.failed = failed.headers["location"].rsplit("/", 1)[1]
        wait_for(runs, self.failed, {"failed"})
        self.models.fail = ()
        self.signed = start_run(self.world, "USR-001", **WINDOW)
        record_all(self.world, self.signed)
        request = runs.review_request(self.signed)
        client.post(
            run_path(self.signed, "sign"),
            data={"brief_digest": request.brief_digest, "outcome": "signed"},
        )
        self.waiting = start_run(self.world, "USR-001")
        self.gate = threading.Event()
        self.models.hold = self.gate
        running = client.post(f"{PREFIX}/runs", data={"user_id": "USR-002"})
        self.running = running.headers["location"].rsplit("/", 1)[1]
        self.running_server = serve(self.world.app)
        self.base_url = self.running_server.base_url
        self.app = self.world.app

    def pages(self) -> dict[str, str]:
        """Every route the application serves for the topic, by name."""
        return {
            "start": f"{PREFIX}/",
            "running": run_path(self.running),
            "failed": run_path(self.failed),
            "review": run_path(self.waiting, "review"),
            "review-open": run_path(self.waiting, "review") + "?tx=TX-1003",
            "questions": run_path(self.waiting, "review") + "?tab=questions",
            "history": run_path(self.waiting, "review") + "?tab=history",
            "signoff": run_path(self.waiting, "review") + "?tab=signoff",
            "signed": run_path(self.signed, "signed") + "?tx=TX-1005",
        }

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
        """Release the held run and stop the server by its own handle."""
        self.gate.set()
        wait_for(self.world.runs, self.running, {"awaiting_review", "failed"})
        self.running_server.stop()


def shot(page, name: str, size: tuple[int, int]) -> None:
    """Save a screenshot for a person when SHOTS_DIR is set."""
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"{name}-{size[0]}.png"))
