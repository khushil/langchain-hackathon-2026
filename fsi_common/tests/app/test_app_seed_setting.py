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


def test_a_list_of_names_makes_the_starting_work_of_each_topic_named_once_in_order(tmp_path):
    calls = []
    topics = [make_topic(tmp_path, n, lambda n=n: calls.append(n)) for n in ("one", "two", "three")]
    config = AppConfig(secret=b"t", topic_folders=(), seed="three, one,,three")
    create_app(config, topics=topics)
    assert calls == ["three", "one"]


def test_a_name_with_no_comma_behaves_as_it_did(tmp_path):
    calls = []
    topics = [make_topic(tmp_path, n, lambda n=n: calls.append(n)) for n in ("one", "two")]
    create_app(AppConfig(secret=b"t", topic_folders=(), seed="two"), topics=topics)
    assert calls == ["two"]


def test_one_unknown_name_in_a_list_stops_the_start_and_nothing_is_made(tmp_path):
    calls = []
    topics = [make_topic(tmp_path, n, lambda n=n: calls.append(n)) for n in ("one", "two")]
    config = AppConfig(secret=b"t", topic_folders=(), seed="one,missing,two")
    with pytest.raises(SeedError, match=r"APP_SEED is 'missing'.*topics served: one, two"):
        create_app(config, topics=topics)
    assert calls == []


def test_a_list_that_names_a_topic_with_no_starting_work_stops_the_start_and_nothing_is_made(
    tmp_path,
):
    calls = []
    topics = [
        make_topic(tmp_path, "one", lambda: calls.append("one")),
        make_topic(tmp_path, "two", None),
    ]
    config = AppConfig(secret=b"t", topic_folders=(), seed="one,two")
    with pytest.raises(SeedError, match="topic 'two' has no starting work"):
        create_app(config, topics=topics)
    assert calls == []


def test_the_names_of_the_setting_are_split_trimmed_and_listed_once():
    assert AppConfig(seed="").seeds == ()
    assert AppConfig(seed=" , ").seeds == ()
    assert AppConfig(seed="a").seeds == ("a",)
    assert AppConfig(seed=" a , b,a,, c ").seeds == ("a", "b", "c")


def test_several_unknown_names_are_named_together_and_the_topics_there_are_are_listed(tmp_path):
    topics = [make_topic(tmp_path, n, lambda: None) for n in ("one", "two")]
    config = AppConfig(secret=b"t", topic_folders=(), seed="one,nosuch,oops")
    with pytest.raises(SeedError) as raised:
        create_app(config, topics=topics)
    assert str(raised.value) == (
        "APP_SEED names nosuch and oops, which are not topics served here; "
        "the topics are one and two."
    )
