"""A state folder that cannot be written is told in words with a 503, never as a bare 500."""

from __future__ import annotations

import logging

from review_fakes import FakeRuns, examples_review
from review_fixtures import DANA, TODAY
from review_helpers import BASE, RUN, settle_everything, text_of
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app
from fsi_common.app.session import SessionCodec
from fsi_common.examples.data import build_examples
from review_app.context import Services
from review_app.drafts import DraftFileError, DraftStore
from review_app.plugin import build_plugin
from workflow.run_registry import StateFolderError

PRIVATE = "The pending work could not be kept in /srv/review/state/drafts.sqlite: readonly database"
SENTENCE = "The server could not save your work. Tell the person who runs this server."


class FullDisk(DraftStore):
    """A draft store whose file cannot be written."""

    def put_fact_decision(self, thread_id, decision):
        raise DraftFileError(PRIVATE)


def client_over(runs: FakeRuns, drafts: DraftStore) -> TestClient:
    services = Services(runs=lambda: runs, drafts=drafts, today=lambda: TODAY)
    app = create_app(AppConfig(secret=b"s", topic_folders=()), topics=[build_plugin(services)])
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(app.state.cookie_name, SessionCodec(b"s").encode(DANA))
    return client


def test_a_decision_the_draft_file_cannot_keep_is_answered_with_503_and_the_action_in_words():
    runs = FakeRuns()
    review = examples_review()
    runs.add("run-1", "awaiting_review", review=review)
    page = client_over(runs, FullDisk()).post(
        f"{RUN}/decide",
        data={
            "brief_digest": review.request.brief_digest,
            "fact_id": build_examples().fact_7_1.id,
            "outcome": "accept",
            "reason": "The quote matches the paragraph.",
        },
    )
    assert page.status_code == 503
    words = text_of(page.text)
    assert "Nothing was recorded." in words and SENTENCE in words
    assert "/srv/review" not in page.text and "readonly" not in page.text.lower()
    assert "Traceback" not in page.text


def test_a_brief_the_run_file_cannot_keep_is_answered_with_503_and_the_action_in_words():
    runs = FakeRuns()
    runs.raises["start"] = StateFolderError(PRIVATE)
    page = client_over(runs, DraftStore()).post(
        f"{BASE}/runs", data={"document_id": "PS26-4", "firm_id": "FIRM-001", "sections": ["7"]}
    )
    assert page.status_code == 503
    assert "No brief was started." in text_of(page.text) and SENTENCE in text_of(page.text)
    assert "/srv/review" not in page.text and "readonly" not in page.text.lower()


def test_the_path_and_the_cause_are_logged_with_the_traceback_when_the_page_hides_them(caplog):
    runs = FakeRuns()
    review = examples_review()
    runs.add("run-1", "awaiting_review", review=review)
    with caplog.at_level(logging.ERROR, logger="review_app.context"):
        client_over(runs, FullDisk()).post(
            f"{RUN}/decide",
            data={
                "brief_digest": review.request.brief_digest,
                "fact_id": build_examples().fact_7_1.id,
                "outcome": "accept",
                "reason": "The quote matches the paragraph.",
            },
        )
    logged = [r for r in caplog.records if "/srv/review/state/drafts.sqlite" in r.getMessage()]
    assert len(logged) == 1 and logged[0].exc_info is not None


class RefusesToClear(DraftStore):
    """A draft store that keeps work but cannot clear it, as after a file turns read-only."""

    def clear(self, thread_id):
        raise DraftFileError(PRIVATE)


def test_a_brief_signed_is_shown_as_signed_when_only_the_clean_up_of_drafts_is_refused(caplog):
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=examples_review())
    client = client_over(runs, RefusesToClear())
    review = settle_everything(client, runs)
    with caplog.at_level(logging.ERROR, logger="review_app.routes_review"):
        reply = client.post(
            f"{RUN}/sign", data={"brief_digest": review.request.brief_digest, "outcome": "signed"}
        )
    assert reply.status_code == 303 and reply.headers["location"] == f"{RUN}/signed"
    assert runs.status("run-1") == "signed" and len(runs.submitted) == 1
    logged = [r for r in caplog.records if r.exc_info is not None]
    assert len(logged) == 1 and "run-1" in logged[0].getMessage()
