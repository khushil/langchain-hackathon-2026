"""The compliance brief's part of the home page: what waits for a reviewer, from the run service."""

from __future__ import annotations

import re

from review_fakes import FakeRuns, examples_review
from review_fixtures import DANA, TODAY, make_client
from review_helpers import BASE, finish

from fsi_common.app import AppConfig, create_app
from review_app.context import Services
from review_app.plugin import build_plugin
from review_app.service import EngineMissingError


def two_waiting_one_signed() -> FakeRuns:
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=examples_review())
    finish(runs, "run-2", [], DANA, on=TODAY)
    runs.add("run-3", "awaiting_review", review=examples_review())
    return runs


def tiles(html: str) -> list[tuple[str, str]]:
    found = re.findall(r'data-hook="tile".*?tile-value">(.*?)<.*?tile-label">(.*?)<', html, re.S)
    return [(label, value) for value, label in found]


def test_the_plug_in_counts_the_runs_that_wait_for_a_reviewer():
    plugin = build_plugin(Services(runs=lambda: two_waiting_one_signed()))
    assert plugin.waiting() == 2
    assert plugin.waiting_noun == "brief"
    assert plugin.list_href == f"{BASE}/"


def test_the_plug_in_counts_nought_when_no_run_has_been_started():
    assert build_plugin(Services(runs=lambda: FakeRuns())).waiting() == 0


def test_the_plug_in_does_not_count_runs_being_written_stopped_signed_or_returned():
    runs = FakeRuns()
    request = {"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "x", "sections": ["7"]}
    runs.add("run-1", "running", request=request)
    runs.add("run-2", "failed", request=request, error="No answer.")
    finish(runs, "run-3", [], DANA, on=TODAY)
    finish(runs, "run-4", [], DANA, on=TODAY, outcome="returned")
    assert build_plugin(Services(runs=lambda: runs)).waiting() == 0


def test_the_plug_in_says_it_cannot_count_when_the_engine_is_not_part_of_the_build():
    def no_engine():
        raise EngineMissingError("The engine that writes briefs is not part of this build.")

    assert build_plugin(Services(runs=no_engine)).waiting() is None


def test_the_home_page_leads_with_the_briefs_waiting_and_links_the_tile_to_the_list():
    page = make_client(two_waiting_one_signed()).get("/")
    assert "2 briefs are waiting for a reviewer." in page.text
    assert tiles(page.text) == [("Compliance brief", "2")]
    assert f'href="{BASE}/"' in page.text
    assert not re.search(r"\bbuilt\b", re.sub(r"<[^>]+>", " ", page.text))


def test_the_home_page_and_the_topics_own_page_count_the_same_waiting_briefs():
    client = make_client(two_waiting_one_signed())
    home = client.get("/").text
    topic = client.get(f"{BASE}/").text
    on_home = int(tiles(home)[0][1])
    on_topic = int(dict(tiles(topic))["Waiting for a reviewer"])
    assert on_home == on_topic == 2


def test_the_home_page_follows_a_brief_as_it_is_signed():
    runs = two_waiting_one_signed()
    client = make_client(runs)
    assert "2 briefs are waiting for a reviewer." in client.get("/").text
    runs._runs["run-1"].status = "signed"
    assert "1 brief is waiting for a reviewer." in client.get("/").text
    runs._runs["run-3"].status = "signed"
    assert "No brief is waiting for a reviewer." in client.get("/").text


def test_the_home_page_names_the_topic_in_words_when_the_engine_is_missing():
    def no_engine():
        raise EngineMissingError("The engine that writes briefs is not part of this build.")

    app = create_app(
        AppConfig(secret=b"test", topic_folders=()),
        topics=[build_plugin(Services(runs=no_engine))],
    )
    from starlette.testclient import TestClient

    page = TestClient(app).get("/")
    assert page.status_code == 200
    assert "Compliance brief cannot say what is waiting." in page.text
