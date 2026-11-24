"""The seed setting: a topic's starting work is made only when the setting names the topic."""

from __future__ import annotations

from pathlib import Path

import pytest

from fsi_common.app import AppConfig, SeedError, TopicPlugin, create_app


def make_topic(root: Path, name: str, seed) -> TopicPlugin:
    return TopicPlugin(
        name=name,
        title=name.capitalize(),
        summary="A topic.",
        prefix=f"/{name}",
        routes=[],
        templates_dir=root,
        seed=seed,
    )


def test_the_environment_names_the_seed_and_without_it_there_is_none():
    assert AppConfig.from_env({"APP_TOPICS": ""}).seed == ""
    assert AppConfig.from_env({"APP_TOPICS": "", "APP_SEED": " compliance-brief "}).seed == (
        "compliance-brief"
    )


def test_no_setting_means_no_topic_makes_its_starting_work(tmp_path):
    calls = []
    topic = make_topic(tmp_path, "one", lambda: calls.append("one"))
    create_app(AppConfig(secret=b"t", topic_folders=()), topics=[topic])
    assert calls == []


def test_the_setting_makes_the_named_topics_starting_work_once_and_no_other(tmp_path):
    calls = []
    one = make_topic(tmp_path, "one", lambda: calls.append("one"))
    two = make_topic(tmp_path, "two", lambda: calls.append("two"))
    create_app(AppConfig(secret=b"t", topic_folders=(), seed="two"), topics=[one, two])
    assert calls == ["two"]


def test_a_setting_that_names_no_served_topic_stops_the_start_in_words(tmp_path):
    topic = make_topic(tmp_path, "one", lambda: None)
    config = AppConfig(secret=b"t", topic_folders=(), seed="missing")
    with pytest.raises(SeedError, match=r"APP_SEED is 'missing'.*topics served: one"):
        create_app(config, topics=[topic])


def test_a_setting_that_names_a_topic_with_no_seed_stops_the_start_in_words(tmp_path):
    topic = make_topic(tmp_path, "one", None)
    config = AppConfig(secret=b"t", topic_folders=(), seed="one")
    with pytest.raises(SeedError, match="topic 'one' has no starting work to make"):
        create_app(config, topics=[topic])


def test_a_failure_of_the_starting_work_stops_the_start_and_is_not_hidden(tmp_path):
    def broken():
        raise SeedError("The recording for the brief is missing.")

    topic = make_topic(tmp_path, "one", broken)
    with pytest.raises(SeedError, match="recording for the brief is missing"):
        create_app(AppConfig(secret=b"t", topic_folders=(), seed="one"), topics=[topic])
