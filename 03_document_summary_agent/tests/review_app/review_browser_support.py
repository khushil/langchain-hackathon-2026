"""A real browser and a served application for the compliance brief's browser tests."""

from __future__ import annotations

import os
from pathlib import Path

from review_fakes import FakeRuns, section_seven_review
from review_fixtures import DANA, TODAY

from fsi_common.app import AppConfig, create_app
from fsi_common.app.browser_checks import RECORD_CLICKS
from fsi_common.app.session import SessionCodec
from fsi_common.app.testing import serve
from fsi_common.records import Decision, SignOff
from review_app.context import Services
from review_app.drafts import DraftStore
from review_app.plugin import build_plugin
from utils.state import ReviewResponse

SIZES = ((1366, 768), (1920, 1080))
SHOTS = os.environ.get("SHOTS_DIR")
SECRET = b"browser-secret"
REQUEST = {"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "x", "sections": ["7"]}


def sign_all(runs: FakeRuns, thread: str) -> None:
    """Decide every fact, answer nothing and sign a run, as the review route would."""
    review = runs._runs[thread].review
    facts = [c.fact for s in review.request.statements for c in s.facts]
    decisions = [
        Decision.on(f, outcome="accept", reason="Matches the paragraph.", reviewer=DANA, date=TODAY)
        for f in facts
    ]
    sign_off = SignOff.build(
        brief_id=review.request.brief_id,
        brief_digest=review.request.brief_digest,
        reviewer=DANA,
        date=TODAY,
        outcome="signed",
        assumptions=[{"question_id": review.question.id, "words": "Treat the services as listed."}],
    )
    runs.submit(thread, ReviewResponse(reviewer=DANA, decisions=decisions, sign_off=sign_off))


def build_runs() -> FakeRuns:
    """Four runs: waiting for review, being written, stopped, and signed."""
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=section_seven_review())
    runs.add(
        "run-2", "running", request={**REQUEST, "sections": ["6", "7"]}, section_results={"6": {}}
    )
    runs.add("run-3", "failed", request=REQUEST, error="Section 7 could not be read: no answer.")
    runs.add("run-4", "awaiting_review", review=section_seven_review(text_suffix=" "))
    sign_all(runs, "run-4")
    return runs


class Served:
    """The application served for a browser, with the fake service behind it."""

    def __init__(self, runs: FakeRuns) -> None:
        self.runs = runs
        services = Services(runs=lambda: runs, drafts=DraftStore(), today=lambda: TODAY)
        self.app = create_app(
            AppConfig(secret=SECRET, topic_folders=()), topics=[build_plugin(services)]
        )
        self.running = serve(self.app)
        self.base_url = self.running.base_url

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
        """Stop the server by its own handle."""
        self.running.stop()


def shot(page, name: str, size: tuple[int, int]) -> None:
    """Save a screenshot for a person when SHOTS_DIR is set."""
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"{name}-{size[0]}.png"))
