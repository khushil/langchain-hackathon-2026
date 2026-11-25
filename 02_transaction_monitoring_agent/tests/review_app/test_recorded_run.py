"""The application on the saved calls: the seed, the offline file and the README's call counts."""

from __future__ import annotations

import json
import re

import pytest
from review_offline_support import RealExport, body_text
from review_support import DANA, marks, run_path, text
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app
from fsi_common.app.offline import export_pages
from fsi_common.app.session import SessionCodec
from fsi_common.records import Decision
from review_app.context import Services
from review_app.drafts import DraftStore
from review_app.offline import HOOK, build_app
from review_app.plugin import build_plugin
from review_app.seed import SEED_DATE, seed_transaction_monitoring
from review_app.seed_fixture import DECISIONS
from utils import PROJECT_ROOT
from workflow.runs import MonitorRuns

SECRET = b"recorded"


@pytest.fixture(scope="module")
def recorded():
    """The application over the saved calls, seeded through its own routes."""
    runs = MonitorRuns(models=None)
    services = Services(runs=lambda: runs, drafts=DraftStore(), today=lambda: SEED_DATE)
    app = create_app(AppConfig(secret=SECRET, topic_folders=()), topics=[build_plugin(services)])
    seed_transaction_monitoring(services, build_plugin)
    cookie = {app.state.cookie_name: SessionCodec(SECRET).encode(DANA)}
    client = TestClient(app, cookies=cookie, follow_redirects=False)
    yield client, runs
    runs.close()
    services.drafts.close()


def test_the_seed_on_the_saved_calls_makes_a_signed_run_and_a_waiting_run(recorded):
    _, runs = recorded
    assert [runs.status(t) for t in reversed(runs.list_runs())] == ["signed", "awaiting_review"]


def test_the_signed_run_holds_the_six_decisions_the_fixture_wrote_by_the_named_person(recorded):
    _, runs = recorded
    held = runs.result(runs.list_runs()[-1])
    decisions = [Decision.model_validate(d) for d in held["decisions"].values()]
    assert len(decisions) == len(DECISIONS) == 6
    assert {d.reviewer.name for d in decisions} == {"Dana Whitfield"}
    assert held["sign_off"]["outcome"] == "signed"


def test_the_waiting_run_arrives_with_six_carried_and_four_waiting_for_a_person(recorded):
    client, runs = recorded
    page = client.get(run_path(runs.list_runs()[0], "review"))
    assert marks(page, "carried") == 6 and marks(page, "needs") == 4
    assert "4 still need your decision" in text(page)


def test_the_home_page_counts_the_one_waiting_review(recorded):
    client, _ = recorded
    assert "1 customer review is waiting for a reviewer" in text(client.get("/"))


def test_the_recordings_folder_holds_what_the_readme_says():
    files = sorted((PROJECT_ROOT / "recordings").glob("*.json"))
    models = [json.loads(f.read_text(encoding="utf-8"))["request"]["model"] for f in files]
    assert (len(files), models.count("claude-sonnet-5-5"), models.count("claude-opus-5-5")) == (
        94,
        78,
        16,
    )
    readme = (PROJECT_ROOT.parent / "README.md").read_text(encoding="utf-8")
    assert "94 calls, 78 on Sonnet that assess transactions and 16 on Opus that judge" in readme


@pytest.fixture(scope="module")
def offline(tmp_path_factory) -> RealExport:
    captured: dict[str, TestClient] = {}

    def prepare(client: TestClient) -> str:
        captured["client"] = client
        return HOOK.seed(client)

    exported = export_pages(build_app(), prepare)
    path = tmp_path_factory.mktemp("recorded-offline") / "monitoring.html"
    path.write_text(exported.html, encoding="utf-8")
    return RealExport(exported, captured["client"], path)


def test_the_offline_file_from_the_saved_calls_holds_every_transaction_and_no_control(offline):
    page = offline.export.html
    for number in ("TX-1001", "TX-1005", "TX-1009", "TX-2004"):
        assert number in page or number in body_text(page), number
    assert "<form" not in page and "<button" not in page
    assert not re.search(r"https?://", page)


def test_the_offline_file_opens_on_the_waiting_review_and_says_what_waits(offline):
    assert "4 still need your decision" in body_text(offline.export.html)


def test_exporting_the_saved_calls_twice_gives_the_same_bytes(offline, tmp_path):
    again = export_pages(build_app(), HOOK.seed)
    assert again.html == offline.export.html


def test_every_saved_call_is_at_medium_effort_as_both_readmes_say():
    efforts = {
        json.loads(f.read_text(encoding="utf-8"))["request"]["effort"]
        for f in (PROJECT_ROOT / "recordings").glob("*.json")
    }
    assert efforts == {"medium"}
    readme = (PROJECT_ROOT.parent / "README.md").read_text(encoding="utf-8")
    running = readme.split("### Running transaction monitoring", 1)[1].split("\n## ", 1)[0]
    assert "78 on Sonnet that assess transactions and 16 on Opus that judge" in running
    assert "each at medium effort" in running


def test_the_topic_readme_gives_the_counts_of_the_recordings_folder():
    topic = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    files = sorted((PROJECT_ROOT / "recordings").glob("*.json"))
    models = [json.loads(f.read_text(encoding="utf-8"))["request"]["model"] for f in files]
    sentence = (
        f"holds {len(files)} saved model calls, {models.count('claude-sonnet-5-5')} on Sonnet "
        f"that assess transactions and {models.count('claude-opus-5-5')} on Opus that judge"
    )
    assert sentence in topic
