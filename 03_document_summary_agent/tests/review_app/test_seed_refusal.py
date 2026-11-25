"""A refused seed advises no step that can lose a signed brief."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, SeedError, create_app
from fsi_common.app.session import SessionCodec
from review_app import seed as seed_module
from review_app.context import Services
from review_app.drafts import DraftStore
from review_app.plugin import build_plugin
from review_app.seed import MARKER_FILE, REVIEWER, SECRET

SEED_NAME = "compliance-brief"
COMMAND = re.compile(r"`((?:[A-Z_]+=\S+ )+make serve)`")
"""A printed command: environment settings and ``make serve``, nothing that can delete or move."""
DESTRUCTIVE = re.compile(r"\b(?:delete|remove|rm|mv|move|overwrite|reset|wipe|clear)\b", re.I)


def start(folder: Path) -> tuple[Services, TestClient]:
    """Start the application as ``make serve`` does, on a state folder, with the seed named."""
    services = Services(drafts=DraftStore())
    config = AppConfig(secret=SECRET, topic_folders=(), seed=SEED_NAME, state_dir=folder)
    try:
        app = create_app(config, topics=[build_plugin(services)])
    except SeedError:
        services.runs().close()
        services.drafts.close()
        raise
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(app.state.cookie_name, SessionCodec(SECRET).encode(REVIEWER))
    return services, client


def stop(services: Services) -> None:
    services.runs().close()
    services.drafts.close()


def signed_record(folder: Path) -> dict:
    """Read the signed brief of a folder without seeding: its sign-off, decisions and digest."""
    from workflow.runs import BriefRuns

    runs = BriefRuns(state_dir=folder)
    try:
        signed = [t for t in runs.list_runs() if runs.status(t) == "signed"]
        assert len(signed) == 1, "the folder should hold exactly one signed brief"
        state = runs.result(signed[0])
        return {
            "thread": signed[0],
            "sign_off": state["sign_off"],
            "decisions": state["decisions"],
            "statuses": sorted(runs.status(t) for t in runs.list_runs()),
        }
    finally:
        runs.close()


@pytest.fixture(scope="module")
def seeded_folder(tmp_path_factory) -> Path:
    """A folder the application has seeded once: one brief waiting and one signed."""
    folder = tmp_path_factory.mktemp("refusal") / "state"
    services, _ = start(folder)
    stop(services)
    return folder


@pytest.fixture()
def folder(seeded_folder, tmp_path) -> Path:
    """A private copy the test may break, holding a signed brief."""
    copy = tmp_path / "state"
    shutil.copytree(seeded_folder, copy)
    return copy


def refusal(folder: Path, monkeypatch) -> str:
    """Change what the seed is made from, as a re-recording does, and return the refusal."""
    monkeypatch.setattr(seed_module, "seed_identity", lambda: "sha256:" + "0" * 64)
    with pytest.raises(SeedError) as caught:
        start(folder)
    return str(caught.value)


def test_the_refusal_names_the_folder_and_what_it_holds(folder, monkeypatch):
    words = refusal(folder, monkeypatch)
    assert f"The state folder {folder} holds 2 briefs, 1 of them signed" in words


def test_the_refusal_advises_no_delete_and_no_move(folder, monkeypatch):
    words = refusal(folder, monkeypatch)
    assert DESTRUCTIVE.search(words) is None, words


def test_the_refusal_offers_a_fresh_folder_by_name_and_says_this_one_is_kept(folder, monkeypatch):
    words = refusal(folder, monkeypatch)
    assert "Nothing in it is changed" in words
    commands = COMMAND.findall(words)
    assert len(commands) == 1, words
    fresh = re.search(r"APP_STATE_DIR=(\S+)", commands[0]).group(1)
    assert fresh != str(folder) and not Path(fresh).exists()
    assert Path(fresh).parent == folder.parent


def test_a_signed_brief_survives_every_command_the_refusal_prints(folder, monkeypatch, tmp_path):
    before = signed_record(folder)
    marker = (folder / MARKER_FILE).read_text()
    words = refusal(folder, monkeypatch)
    commands = COMMAND.findall(words)
    assert commands, f"the refusal prints no command to run: {words}"
    monkeypatch.undo()
    for command in commands:
        settings = dict(part.split("=", 1) for part in command.split() if "=" in part)
        target = Path(settings["APP_STATE_DIR"])
        assert settings["APP_SEED"] == SEED_NAME
        services, _ = start(target)  # what `make serve` does with those settings
        stop(services)
        assert len(signed_record(target)["statuses"]) == 2
    assert signed_record(folder) == before
    assert (folder / MARKER_FILE).read_text() == marker
    assert json.loads(marker)["seed"] == SEED_NAME


def test_the_fresh_folder_name_skips_a_folder_that_exists(tmp_path):
    taken = tmp_path / "state"
    (tmp_path / "state-2").mkdir()
    assert seed_module.fresh_folder(taken) == tmp_path / "state-3"


def test_a_folder_with_runs_and_no_marker_is_refused_with_the_same_safe_words(folder):
    (folder / MARKER_FILE).unlink()
    with pytest.raises(SeedError) as caught:
        start(folder)
    words = str(caught.value)
    assert "holds 2 briefs, 1 of them signed" in words
    assert COMMAND.search(words) and "delete" not in words.lower()
    assert signed_record(folder)["statuses"] == ["awaiting_review", "signed"]


@pytest.mark.parametrize(
    "advice",
    [
        "delete the folder /x/state to start afresh.",
        "Run `rm -rf /x/state` and start again.",
        "Run `mv /x/state /x/old` first.",
    ],
)
def test_the_scan_sees_the_old_advice_and_any_delete_or_move_in_planted_words(advice):
    assert DESTRUCTIVE.search(advice) is not None
    assert COMMAND.search(advice) is None
