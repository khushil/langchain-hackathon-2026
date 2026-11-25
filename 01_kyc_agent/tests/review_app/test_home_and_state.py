"""The home page counts what waits here, and the topic keeps its state in a folder when asked."""

import re

import pytest
from kyc_fakes import ScriptedReader
from starlette.testclient import TestClient
from support import (
    BASE,
    DANA,
    SECRET,
    SMALL,
    make_client,
    make_services,
    new_runs,
    settle_all,
    start_run,
    text_of,
)

from fsi_common.app import AppConfig, create_app
from fsi_common.app.session import SessionCodec
from review_app import service
from review_app.context import Services
from review_app.drafts import DraftFileError, DraftStore
from review_app.plugin import build_plugin
from review_app.service import EngineMissingError


@pytest.fixture()
def scripted():
    service.use_models(ScriptedReader())
    yield
    service.use_models(None)


def test_the_plug_in_counts_the_batches_that_wait_for_a_reviewer():
    runs = new_runs()
    start_run(runs, ["CUST-001"])
    start_run(runs, ["CUST-004"])
    plugin = build_plugin(make_services(runs))
    assert plugin.waiting() == 2
    assert plugin.waiting_noun == "batch"
    assert plugin.list_href == f"{BASE}/"
    assert (plugin.name, plugin.title, plugin.prefix) == (
        "kyc-onboarding",
        "KYC onboarding",
        "/kyc",
    )


def test_the_plug_in_counts_nought_for_no_batch_and_not_a_signed_one():
    runs = new_runs()
    assert build_plugin(make_services(runs)).waiting() == 0
    thread = start_run(runs, ["CUST-001"])
    client = make_client(runs)
    settle_all(client, runs, thread)
    digest = runs.review_request(thread).brief_digest
    client.post(f"{BASE}/runs/{thread}/sign", data={"brief_digest": digest, "outcome": "signed"})
    assert build_plugin(make_services(runs)).waiting() == 0


def test_the_plug_in_says_it_cannot_count_when_the_engine_is_not_part_of_the_build():
    def no_engine():
        raise EngineMissingError("The engine is not part of this build.")

    assert build_plugin(Services(runs=no_engine)).waiting() is None


def test_the_home_page_leads_with_the_batches_waiting_and_links_the_tile_to_the_list():
    runs = new_runs()
    start_run(runs, ["CUST-001"])
    page = make_client(runs).get("/")
    assert "1 batch is waiting for a reviewer." in text_of(page.text)
    assert re.search(
        r'href="/kyc/"[^>]*data-hook="tile"|data-hook="tile"[^>]*href="/kyc/"', page.text
    )


def test_the_about_page_says_what_the_data_is_and_the_advice_sentence_only_in_the_shell():
    page = make_client(new_runs()).get("/about")
    text = text_of(page.text)
    assert "KYC onboarding" in text and "Nothing is decided for them." in text
    from review_app.plugin import ABOUT

    assert not any("not legal, compliance or regulatory advice" in p for p in ABOUT)
    assert text.count("not legal, compliance or regulatory advice") == 1


def test_a_state_folder_keeps_batches_decisions_and_drafts_across_a_restart(tmp_path, scripted):
    config = AppConfig(secret=SECRET, topic_folders=(), state_dir=tmp_path / "state")
    (tmp_path / "state").mkdir()
    first_services = Services()
    first = create_app(config, topics=[build_plugin(first_services)])
    cookie = SessionCodec(SECRET).encode(DANA)
    client = TestClient(first, cookies={first.state.cookie_name: cookie}, follow_redirects=False)
    runs = first_services.runs()
    thread = start_run(runs, SMALL)
    request = runs.review_request(thread)
    proposal = next(
        c.fact for s in request.statements for c in s.facts if c.fact.kind == "proposal"
    )
    done = client.post(
        f"{BASE}/runs/{thread}/decide",
        data={
            "brief_digest": request.brief_digest,
            "fact_id": proposal.id,
            "outcome": "accept",
            "reason": "Checked.",
        },
    )
    assert done.status_code == 303
    runs.close()
    first_services.drafts.close()
    second_services = Services()
    second = create_app(config, topics=[build_plugin(second_services)])
    again = TestClient(second, cookies={second.state.cookie_name: cookie}, follow_redirects=False)
    assert second_services.runs().status(thread) == "awaiting_review"
    assert "1 of 4" in text_of(again.get(f"{BASE}/runs/{thread}/review").text)
    second_services.runs().close()
    second_services.drafts.close()


def test_a_state_folder_that_cannot_be_written_stops_the_page_in_words(tmp_path):
    runs = new_runs()
    thread = start_run(runs, ["CUST-001"])

    class Broken(DraftStore):
        def put_fact_decision(self, thread_id, decision):
            raise DraftFileError("disk full at /secret/place")

    services = Services(runs=lambda: runs, drafts=Broken(), today=lambda: "2026-11-25")
    client = make_client(runs, services=services)
    request = runs.review_request(thread)
    proposal = next(
        c.fact for s in request.statements for c in s.facts if c.fact.kind == "proposal"
    )
    refused = client.post(
        f"{BASE}/runs/{thread}/decide",
        data={
            "brief_digest": request.brief_digest,
            "fact_id": proposal.id,
            "outcome": "accept",
            "reason": "x",
        },
    )
    assert refused.status_code == 503
    assert "Nothing was recorded." in refused.text and "/secret/place" not in refused.text
