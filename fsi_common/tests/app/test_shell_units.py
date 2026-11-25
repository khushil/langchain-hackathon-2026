"""The shell's small parts without a process: topic facts, the topic list header, the home words."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fsi_common.app.home import HomeEntry, HomeSummary
from fsi_common.app.proxy import forward_headers
from fsi_common.app.topic_info import (
    PEERS_HEADER,
    TopicInfo,
    decode_peers,
    encode_peers,
    title_from_folder,
)


def info(name: str, prefix: str | None = None, title: str | None = None) -> TopicInfo:
    return TopicInfo(
        name=name,
        title=title or name.capitalize(),
        summary="s",
        prefix=prefix or f"/{name}",
        about=("a",),
        waiting_noun="case",
    )


@pytest.mark.parametrize(
    ("folder", "title"),
    [
        ("02_transaction_monitoring_agent", "Transaction monitoring"),
        ("03_document_summary_agent", "Document summary"),
        ("01_kyc_agent", "Kyc"),
        ("toy_topic", "Toy topic"),
        ("7", "7"),
    ],
)
def test_a_title_made_from_a_folder_name_drops_the_number_and_the_agent_suffix(folder, title):
    assert title_from_folder(Path("/x") / folder) == title


def test_the_topic_list_header_carries_name_title_and_prefix_and_reads_back_the_same():
    sent = [info("alpha", title="Café, one"), info("beta")]
    value = encode_peers(sent)
    value.encode("ascii")
    back = decode_peers(value)
    assert [(t.name, t.title, t.prefix) for t in back] == [
        ("alpha", "Café, one", "/alpha"),
        ("beta", "Beta", "/beta"),
    ]


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "not json",
        json.dumps({"a": 1}),
        json.dumps([{"name": "x", "title": "X", "prefix": "https://evil.example"}]),
        json.dumps([{"name": "x", "title": "X", "prefix": "//evil"}]),
        json.dumps([{"name": "x", "title": "X", "prefix": "/a/b"}]),
        json.dumps([{"name": "x", "title": "X"}]),
    ],
)
def test_a_topic_list_header_that_is_absent_or_wrong_gives_no_topics(value):
    assert decode_peers(value) == ()


def test_the_headers_forwarded_to_a_topic_drop_hop_by_hop_ones_and_a_clients_own_topic_list():
    sent = [
        (b"host", b"example.test:4803"),
        (b"cookie", b"a=1"),
        (b"connection", b"keep-alive"),
        (b"transfer-encoding", b"chunked"),
        (b"content-length", b"3"),
        (PEERS_HEADER.encode(), b"[]"),
        (b"x-other", b"1"),
    ]
    listed = forward_headers(sent, [info("alpha")])
    assert [name for name, _ in listed].count(PEERS_HEADER) == 1
    got = dict(listed)
    assert got["host"] == "example.test:4803" and got["cookie"] == "a=1" and got["x-other"] == "1"
    assert not {"connection", "transfer-encoding", "content-length"} & set(got)
    assert decode_peers(got[PEERS_HEADER])[0].prefix == "/alpha"


def entry(
    title: str,
    waiting: int | None,
    *,
    reachable: bool = True,
    noun: str = "case",
    starting: bool = False,
):
    return HomeEntry(
        title, f"/{title.lower()}/", noun, waiting, reachable=reachable, starting=starting
    )


def test_a_topic_that_could_not_be_reached_is_named_and_the_others_are_still_counted():
    summary = HomeSummary((entry("Alpha", 2), entry("Beta", None, reachable=False)))
    assert summary.sentence() == "2 cases are waiting for a reviewer. Beta could not be reached."
    tiles = summary.tiles()
    assert [(t.label, t.value) for t in tiles] == [("Alpha", "2"), ("Beta", "Not available")]


def test_two_topics_that_could_not_be_reached_are_named_together():
    summary = HomeSummary(
        (entry("Alpha", None, reachable=False), entry("Beta", None, reachable=False))
    )
    assert summary.sentence() == "Alpha and Beta could not be reached."


def test_a_topic_that_cannot_say_what_waits_is_still_told_apart_from_one_not_reached():
    summary = HomeSummary((entry("Alpha", None), entry("Beta", 0)))
    assert (
        summary.sentence() == "No case is waiting for a reviewer. Alpha cannot say what is waiting."
    )


@pytest.mark.parametrize(
    ("noun", "one", "two"),
    [
        ("case", "1 case", "2 cases"),
        ("batch", "1 batch", "2 batches"),
        ("match", "1 match", "2 matches"),
        ("box", "1 box", "2 boxes"),
        ("query", "1 query", "2 queries"),
        ("day", "1 day", "2 days"),
    ],
)
def test_the_home_sentence_spells_the_plural_of_a_noun_that_ends_in_a_sibilant_or_y(noun, one, two):
    assert HomeSummary((entry("Alpha", 1, noun=noun),)).sentence() == (
        f"{one} is waiting for a reviewer."
    )
    assert HomeSummary((entry("Alpha", 2, noun=noun),)).sentence() == (
        f"{two} are waiting for a reviewer."
    )


@pytest.mark.parametrize("value", ["0", "-1", "x", "nan", ""])
def test_a_start_wait_that_is_not_a_number_above_nought_is_refused_in_words(value):
    from fsi_common.app import ConfigError
    from fsi_common.app.config import AppConfig

    with pytest.raises(ConfigError, match="APP_CHILD_START_SECONDS"):
        AppConfig.from_env({"APP_TOPICS": "", "APP_CHILD_START_SECONDS": value})


def test_a_start_wait_above_nought_is_read():
    from fsi_common.app.config import AppConfig

    config = AppConfig.from_env({"APP_TOPICS": "", "APP_CHILD_START_SECONDS": "2.5"})
    assert config.child_start_seconds == 2.5


def test_two_folders_of_one_name_are_refused_so_two_topics_never_share_a_state_folder(tmp_path):
    from app_probe_topic import make_probe_topic

    from fsi_common.app import AppConfig, TopicLoadError
    from fsi_common.app.shell import create_shell

    one = make_probe_topic(tmp_path / "a", "01_alpha_agent", name="alpha", value="a")
    two = make_probe_topic(tmp_path / "b", "01_alpha_agent", name="beta", value="b")
    with pytest.raises(TopicLoadError, match="share the name 01_alpha_agent"):
        create_shell(AppConfig(secret=b"x", topic_folders=(one, two)))


def test_the_processes_are_started_on_the_thread_that_runs_the_shell(tmp_path, monkeypatch):
    """A process is tied to the thread that started it, so a pool thread that ends would end it."""
    import asyncio
    import threading

    from app_probe_topic import make_probe_topic

    from fsi_common.app import AppConfig
    from fsi_common.app.children import TopicChild
    from fsi_common.app.shell import Shell

    started: list[int] = []
    monkeypatch.setattr(
        TopicChild, "start", lambda self, config: started.append(threading.get_ident())
    )
    folder = make_probe_topic(tmp_path, "01_alpha_agent", name="alpha", value="a")
    shell = Shell(AppConfig(secret=b"x", topic_folders=(folder,)), [folder])
    asyncio.run(shell.start())
    assert started == [threading.get_ident()]


def test_a_topic_that_is_starting_again_is_said_to_be_and_not_to_be_lost():
    summary = HomeSummary(
        (
            entry("Alpha", 2),
            entry("Beta", None, reachable=False, starting=True),
            entry("Gamma", None, reachable=False),
        )
    )
    assert summary.sentence() == (
        "2 cases are waiting for a reviewer. Gamma could not be reached. Beta is starting again."
    )


def test_two_folders_given_through_a_link_keep_two_state_folders(tmp_path):
    from app_probe_topic import make_probe_topic

    from fsi_common.app import AppConfig
    from fsi_common.app.children import make_children

    real = make_probe_topic(tmp_path / "a", "toy", name="alpha", value="a")
    (tmp_path / "links").mkdir()
    link = tmp_path / "links" / "x"
    link.symlink_to(real, target_is_directory=True)
    other = make_probe_topic(tmp_path / "b", "x", name="beta", value="b")
    config = AppConfig(secret=b"s", topic_folders=(), state_dir=tmp_path / "state")
    children = make_children(config, [link, other])
    assert children[0].state != children[1].state
    assert children[0].state == tmp_path / "state" / "toy"


def test_a_folder_given_twice_once_through_a_link_is_refused_by_name(tmp_path):
    from app_probe_topic import make_probe_topic

    from fsi_common.app import AppConfig, TopicLoadError
    from fsi_common.app.shell import create_shell

    real = make_probe_topic(tmp_path / "a", "toy", name="alpha", value="a")
    (tmp_path / "links").mkdir()
    link = tmp_path / "links" / "x"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(TopicLoadError, match="share the name toy"):
        create_shell(AppConfig(secret=b"s", topic_folders=(real, link)))
