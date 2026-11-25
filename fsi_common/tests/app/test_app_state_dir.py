"""The state folder setting: read from the environment, handed to each topic before its seed."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from test_app_seed_setting import make_topic

from fsi_common.app import AppConfig, create_app
from fsi_common.app.config import REPOSITORY_ROOT


def with_hook(root: Path, name: str, calls: list, *, seed=None):
    plugin = make_topic(root, name, seed or (lambda: calls.append(f"seed {name}")))
    return replace(plugin, use_state_dir=lambda path: calls.append(f"state {name} {path}"))


def test_the_environment_names_the_state_folder_and_without_it_there_is_none():
    assert AppConfig.from_env({"APP_TOPICS": ""}).state_dir is None
    assert AppConfig.from_env({"APP_TOPICS": "", "APP_STATE_DIR": " "}).state_dir is None
    found = AppConfig.from_env({"APP_TOPICS": "", "APP_STATE_DIR": "/var/lib/review-desk"})
    assert found.state_dir == Path("/var/lib/review-desk")


def test_each_topic_is_given_the_folder_before_the_seed_is_made(tmp_path):
    calls: list[str] = []
    one = with_hook(tmp_path, "one", calls)
    config = AppConfig(secret=b"t", topic_folders=(), seed="one", state_dir=tmp_path / "state")
    create_app(config, topics=[one])
    assert calls == [f"state one {tmp_path / 'state'}", "seed one"]


def test_every_topic_with_a_hook_is_given_the_folder_and_a_topic_without_one_is_left_alone(
    tmp_path,
):
    calls: list[str] = []
    one = with_hook(tmp_path, "one", calls)
    two = make_topic(tmp_path, "two", None)
    three = with_hook(tmp_path, "three", calls)
    config = AppConfig(secret=b"t", topic_folders=(), state_dir=tmp_path / "s")
    create_app(config, topics=[one, two, three])
    assert calls == [f"state one {tmp_path / 's'}", f"state three {tmp_path / 's'}"]


def test_with_no_folder_no_topic_is_given_one(tmp_path):
    calls: list[str] = []
    create_app(AppConfig(secret=b"t", topic_folders=()), topics=[with_hook(tmp_path, "one", calls)])
    assert calls == []


def test_make_serve_keeps_the_state_in_a_folder_of_the_repository_that_git_ignores():
    makefile = (REPOSITORY_ROOT / "Makefile").read_text()
    serve = re.search(r"^serve:\n((?:\t.*\n)+)", makefile, re.M)
    assert serve is not None and "APP_STATE_DIR=" in serve.group(1)
    folder = re.search(r"^APP_STATE_DIR \?= \$\(CURDIR\)/([\w.-]+)$", makefile, re.M)
    assert folder is not None, "the Makefile names the folder in the repository root"
    ignored = (REPOSITORY_ROOT / ".gitignore").read_text().splitlines()
    assert f"/{folder.group(1)}/" in ignored
