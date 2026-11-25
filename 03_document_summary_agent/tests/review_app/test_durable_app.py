"""The served application on a state folder: a restart shows the same briefs and drafts."""

from __future__ import annotations

import json
import re
import shutil
import threading
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, SeedError, create_app
from fsi_common.app.session import SessionCodec
from review_app import seed as seed_module
from review_app.context import PREFIX, Services
from review_app.drafts import DraftStore
from review_app.plugin import build_plugin
from review_app.seed import DECISIONS, MARKER_FILE, PROFILE, QUESTIONS, REVIEWER, SECRET

SEED_NAME = "compliance-brief"


@dataclass
class Served:
    """The application over one state folder, with its services and a signed-in client."""

    services: Services
    client: TestClient

    @property
    def runs(self):
        return self.services.runs()

    def waiting_and_signed(self) -> tuple[str, str]:
        by_status = {self.runs.status(t): t for t in self.runs.list_runs()}
        return by_status["awaiting_review"], by_status["signed"]

    def stop(self) -> None:
        self.runs.close()
        self.services.drafts.close()


def start(folder: Path, *, seed: bool = True) -> Served:
    services = Services(drafts=DraftStore())
    config = AppConfig(
        secret=SECRET,
        topic_folders=(),
        seed=SEED_NAME if seed else "",
        state_dir=folder,
    )
    try:
        app = create_app(config, topics=[build_plugin(services)])
    except SeedError:
        Served(services, None).stop()  # a process whose start failed ends and lets go of the folder
        raise
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(app.state.cookie_name, SessionCodec(SECRET).encode(REVIEWER))
    return Served(services, client)


def settle_questions(served: Served, thread: str, digest: str) -> None:
    """Answer or accept each open question of the brief through the routes, as the seed does."""
    ids = {q.about.anchor: q.id for q in served.runs.review_request(thread).open_questions}
    for question in QUESTIONS:
        body = {"brief_digest": digest, "question_id": ids[question.paragraph]}
        if question.assumption:
            route, body = "assume", {**body, "words": question.assumption}
        else:
            route, body = "answer", {**body, "answer": question.answer, "reason": question.reason}
        assert served.client.post(f"{PREFIX}/runs/{thread}/{route}", data=body).status_code == 303


def text_of(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def pages_of(served: Served) -> dict[str, str]:
    waiting, signed = served.waiting_and_signed()
    run = f"{PREFIX}/runs"
    paths = {
        "home": "/",
        "list": f"{PREFIX}/",
        "review": f"{run}/{waiting}/review",
        "facts": f"{run}/{waiting}/facts",
        "signed": f"{run}/{signed}/signed",
    }
    pages = {}
    for name, path in paths.items():
        page = served.client.get(path)
        assert page.status_code == 200, (name, page.status_code)
        pages[name] = text_of(page.text)
    return pages


def decide_first_fact(served: Served) -> str:
    waiting, _ = served.waiting_and_signed()
    digest = served.runs.review_request(waiting).brief_digest
    first = DECISIONS[0]
    reply = served.client.post(
        f"{PREFIX}/runs/{waiting}/decide",
        data={
            "brief_digest": digest,
            "fact_id": first.fact_id,
            "outcome": "accept",
            "reason": "I read the paragraph and the quoted words are in it.",
        },
    )
    assert reply.status_code == 303
    return first.fact_id


@pytest.fixture(scope="module")
def seeded_folder(tmp_path_factory) -> Path:
    """A folder the application has seeded once and been stopped on."""
    folder = tmp_path_factory.mktemp("seeded") / "state"
    served = start(folder)
    assert len(served.runs.list_runs()) == 2
    served.stop()
    return folder


@pytest.fixture()
def folder(seeded_folder, tmp_path) -> Path:
    """A private copy of the seeded folder, so a test may change it."""
    copy = tmp_path / "state"
    shutil.copytree(seeded_folder, copy)
    return copy


def test_a_restart_shows_the_same_pages_statuses_decision_and_draft(folder):
    first = start(folder, seed=False)
    fact_id = decide_first_fact(first)
    waiting, signed = first.waiting_and_signed()
    statuses = {t: first.runs.status(t) for t in first.runs.list_runs()}
    signed_state = first.runs.result(signed)
    before = pages_of(first)
    assert "Accepted by you" in before["review"]
    first.stop()
    second = start(folder, seed=False)
    assert {t: second.runs.status(t) for t in second.runs.list_runs()} == statuses
    assert second.waiting_and_signed() == (waiting, signed)
    assert pages_of(second) == before
    held = second.services.drafts.get(waiting, REVIEWER)
    assert set(held.facts) == {fact_id} and held.facts[fact_id].outcome == "accept"
    assert second.runs.result(signed)["decisions"] == signed_state["decisions"]
    assert second.runs.result(signed)["sign_off"] == signed_state["sign_off"]
    second.stop()


def test_starting_with_the_seed_again_adds_no_copy_and_changes_no_decision_or_digest(folder):
    first = start(folder, seed=False)
    waiting, signed = first.waiting_and_signed()
    threads = first.runs.list_runs()
    digest = first.runs.review_request(waiting).brief_digest
    decisions = first.runs.result(signed)["decisions"]
    sign_off = first.runs.result(signed)["sign_off"]
    first.stop()
    again = start(folder, seed=True)
    assert again.runs.list_runs() == threads
    assert again.runs.review_request(waiting).brief_digest == digest
    assert again.runs.result(signed)["decisions"] == decisions
    assert again.runs.result(signed)["sign_off"] == sign_off
    again.stop()


def test_a_seeded_folder_holds_a_brief_waiting_and_a_brief_signed_newest_first(folder):
    served = start(folder, seed=False)
    assert [served.runs.status(t) for t in served.runs.list_runs()] == ["signed", "awaiting_review"]
    waiting, signed = served.waiting_and_signed()
    decided = served.runs.result(signed)["decisions"]
    answered = sum(1 for q in QUESTIONS if q.answer)
    assert len(decided) == len(DECISIONS) + len(PROFILE.fact_ids) + answered
    served.stop()


def test_a_brief_signed_after_a_restart_is_still_signed_after_the_next_and_its_draft_is_gone(
    folder,
):
    first = start(folder, seed=False)
    waiting, _ = first.waiting_and_signed()
    request = first.runs.review_request(waiting)
    first.client.post(
        f"{PREFIX}/runs/{waiting}/profile",
        data={
            "brief_digest": request.brief_digest,
            "outcome": "accept",
            "reason": "The profile matches the tables.",
        },
    )
    first.stop()
    second = start(folder, seed=False)
    assert len(second.services.drafts.get(waiting, REVIEWER).facts) == len(PROFILE.fact_ids)
    for decision in DECISIONS:
        second.client.post(
            f"{PREFIX}/runs/{waiting}/decide",
            data={
                "brief_digest": request.brief_digest,
                "fact_id": decision.fact_id,
                "outcome": "accept",
                "reason": decision.reason,
            },
        )
    settle_questions(second, waiting, request.brief_digest)
    signing = second.client.post(
        f"{PREFIX}/runs/{waiting}/sign",
        data={"brief_digest": request.brief_digest, "outcome": "signed"},
    )
    assert signing.status_code == 303
    second.stop()
    third = start(folder, seed=False)
    assert third.runs.status(waiting) == "signed"
    assert third.services.drafts.get(waiting, REVIEWER).facts == {}
    third.stop()


def test_several_requests_at_once_on_one_folder_meet_no_error_and_lose_no_write(folder):
    served = start(folder, seed=False)
    waiting, _ = served.waiting_and_signed()
    digest = served.runs.review_request(waiting).brief_digest
    app = served.client.app
    failures: list[str] = []

    def work(decision):
        client = TestClient(app, follow_redirects=False)
        client.cookies.set(app.state.cookie_name, SessionCodec(SECRET).encode(REVIEWER))
        body = {
            "brief_digest": digest,
            "fact_id": decision.fact_id,
            "outcome": "accept",
            "reason": decision.reason,
        }
        for step in (
            lambda: client.post(f"{PREFIX}/runs/{waiting}/decide", data=body),
            lambda: client.get(f"{PREFIX}/runs/{waiting}/review"),
            lambda: client.get(f"{PREFIX}/"),
            lambda: client.get("/"),
        ):
            reply = step()
            if reply.status_code not in (200, 303):
                failures.append(f"{reply.request.url} answered {reply.status_code}")

    threads = [threading.Thread(target=work, args=(d,)) for d in DECISIONS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert failures == []
    wanted = {d.fact_id for d in DECISIONS}
    assert set(served.services.drafts.get(waiting, REVIEWER).facts) == wanted
    served.stop()
    again = start(folder, seed=False)
    assert set(again.services.drafts.get(waiting, REVIEWER).facts) == wanted
    again.stop()


def test_a_first_start_that_fails_partway_makes_the_second_start_refuse_the_folder_in_words(
    tmp_path, monkeypatch
):
    folder = tmp_path / "state"
    broken = (replace(DECISIONS[0], fact_id="fact:0000000000000000"), *DECISIONS[1:])
    with monkeypatch.context() as patched:
        patched.setattr(seed_module, "DECISIONS", broken)
        with pytest.raises(SeedError, match="not the one the seed's decisions were written for"):
            start(folder)
    assert not (folder / MARKER_FILE).exists()
    with pytest.raises(SeedError, match=rf"The state folder {folder} holds"):
        start(folder)


def test_a_finished_seed_leaves_a_marker_naming_the_seed_and_what_it_was_made_from(folder):
    marker = json.loads((folder / MARKER_FILE).read_text())
    assert marker["seed"] == SEED_NAME
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", marker["digest"])


def test_a_folder_with_runs_and_no_marker_is_refused_in_words(folder):
    (folder / MARKER_FILE).unlink()
    with pytest.raises(SeedError, match=rf"The state folder {folder} holds"):
        start(folder)


def test_a_folder_seeded_from_other_recordings_is_refused_in_words(folder, monkeypatch):
    monkeypatch.setattr(seed_module, "seed_identity", lambda: "sha256:" + "0" * 64)
    with pytest.raises(SeedError, match=rf"The state folder {folder} holds"):
        start(folder)


def test_a_folder_seeded_from_other_recordings_keeps_its_marker_through_the_refusal(
    folder, monkeypatch
):
    before = (folder / MARKER_FILE).read_text()
    monkeypatch.setattr(seed_module, "seed_identity", lambda: "sha256:" + "0" * 64)
    with pytest.raises(SeedError):
        start(folder)
    assert (folder / MARKER_FILE).read_text() == before
    assert not (folder / f"{MARKER_FILE}.part").exists()


def recordings_copy(tmp_path, monkeypatch) -> Path:
    """Point the seed's recordings at a copy it may change, and return the copy."""
    copy = tmp_path / "recordings"
    shutil.copytree(seed_module.recordings_dir({}), copy)
    monkeypatch.setenv("MODEL_RECORDINGS_DIR", str(copy))
    return copy


def test_the_seeds_identity_changes_when_a_recording_is_added_and_when_one_changes(
    tmp_path, monkeypatch
):
    copy = recordings_copy(tmp_path, monkeypatch)
    same = seed_module.seed_identity()
    assert seed_module.seed_identity() == same
    (copy / "added.json").write_text("{}")
    added = seed_module.seed_identity()
    assert added != same
    (copy / "added.json").write_text('{"changed": true}')
    assert seed_module.seed_identity() not in {same, added}
    (copy / "added.json").unlink()
    assert seed_module.seed_identity() == same


def test_a_folder_seeded_before_a_recording_was_added_is_refused_naming_the_folder(
    tmp_path, monkeypatch
):
    copy = recordings_copy(tmp_path, monkeypatch)
    folder = tmp_path / "state"
    start(folder).stop()
    start(folder).stop()  # the same recordings: no error and no second copy
    (copy / "added.json").write_text("{}")
    with pytest.raises(SeedError, match=rf"The state folder {folder} holds"):
        start(folder)


def test_a_folder_seeded_before_a_recording_changed_is_refused_naming_the_folder(
    tmp_path, monkeypatch
):
    copy = recordings_copy(tmp_path, monkeypatch)
    folder = tmp_path / "state"
    start(folder).stop()
    changed = sorted(copy.glob("*.json"))[0]
    changed.write_text(changed.read_text() + " ")
    with pytest.raises(SeedError, match=rf"The state folder {folder} holds"):
        start(folder)
