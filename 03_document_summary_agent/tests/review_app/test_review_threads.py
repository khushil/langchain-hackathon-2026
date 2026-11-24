"""The pages call the run service off the event loop, and the library is read once."""

from __future__ import annotations

import asyncio

from review_fixtures import DANA, TODAY, make_client
from review_helpers import BASE, RUN, assume, decide, runs_for_every_page, settle_everything

from fsi_common.app import AppConfig, create_app
from fsi_common.app.session import SessionCodec
from fsi_common.examples.data import build_examples
from review_app.context import Services
from review_app.drafts import DraftStore
from review_app.library import read_library
from review_app.plugin import build_plugin

EX = build_examples()


def _use_every_route(client, runs):
    """Fetch every page and export, and post every form, so every handler runs once."""
    review = runs._runs["run-1"].review
    for path in (
        f"{BASE}/",
        f"{BASE}/runs.csv",
        f"{BASE}/runs/run-3",
        f"{BASE}/runs/run-4",
        f"{RUN}",
        f"{RUN}/review",
        f"{RUN}/review?tab=questions",
        f"{RUN}/review?tab=signoff",
        f"{RUN}/facts",
        f"{RUN}/facts.csv",
        f"{BASE}/runs/run-2/signed",
        f"{BASE}/runs/run-2/facts",
        f"{BASE}/runs/run-2/decisions.csv",
    ):
        assert client.get(path).status_code in {200, 303}, path
    decide(client, review, EX.fact_7_1)
    assume(client, review)
    client.post(
        f"{RUN}/answer",
        data={
            "brief_digest": review.request.brief_digest,
            "question_id": review.question.id,
            "answer": "Yes",
            "reason": "Register.",
        },
    )
    settle_everything(client, runs)
    client.post(
        f"{BASE}/runs",
        data={"document_id": "PS26-4", "firm_id": "FIRM-001", "sections": ["7"]},
    )
    client.post(
        f"{RUN}/sign", data={"brief_digest": review.request.brief_digest, "outcome": "signed"}
    )


def test_no_page_calls_the_run_service_on_the_event_loop():
    runs = runs_for_every_page()
    runs._runs["run-3"].status = "signed"  # one live run at most, so that the start is accepted
    _use_every_route(make_client(runs), runs)
    assert runs.calls > 0 and runs.started and runs.submitted
    assert runs.on_loop == []


def test_the_check_on_the_event_loop_sees_a_call_made_there():
    runs = runs_for_every_page()

    async def on_the_loop():
        runs.status("run-1")

    asyncio.run(on_the_loop())
    assert runs.on_loop == ["status"]


def test_the_library_is_read_once_when_the_plugin_is_built_and_never_again():
    reads = []

    def counting():
        reads.append(1)
        return read_library()

    runs = runs_for_every_page()
    runs._runs["run-3"].status = "signed"
    services = Services(
        runs=lambda: runs, library=counting, drafts=DraftStore(), today=lambda: TODAY
    )
    app = create_app(AppConfig(secret=b"s", topic_folders=()), topics=[build_plugin(services)])
    from starlette.testclient import TestClient

    client = TestClient(
        app,
        cookies={app.state.cookie_name: SessionCodec(b"s").encode(DANA)},
        follow_redirects=False,
    )
    assert len(reads) == 1
    _use_every_route(client, runs)
    assert len(reads) == 1
