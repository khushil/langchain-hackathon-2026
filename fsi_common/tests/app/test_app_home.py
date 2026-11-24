"""The home page: what waits for a reviewer across the workflows, as one sentence and its tiles."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, Tile, TopicPlugin, create_app
from fsi_common.app.home import HomeEntry, HomeSummary, summarise_home
from fsi_common.app.pages import MAX_TILES


def make_topic(
    root: Path,
    name: str,
    *,
    waiting,
    noun: str = "brief",
    title: str | None = None,
) -> TopicPlugin:
    """Make a topic that reports a waiting count and has no pages of its own."""
    return TopicPlugin(
        name=name,
        title=title or name.replace("-", " ").capitalize(),
        summary=f"The {name} workflow.",
        prefix=f"/{name}",
        routes=[],
        templates_dir=root,
        waiting=waiting,
        waiting_noun=noun,
    )


def home(tmp_path, *topics: TopicPlugin) -> str:
    app = create_app(AppConfig(secret=b"test", topic_folders=()), topics=list(topics))
    page = TestClient(app).get("/")
    assert page.status_code == 200
    return page.text


def sentence_of(html: str) -> str:
    found = re.search(r'data-hook="sentence">(.*?)</h1>', html, re.S)
    assert found
    return " ".join(found.group(1).split())


def tiles_of(html: str) -> list[dict[str, str]]:
    """Each tile as its link, value and label, read from the markup."""
    out = []
    for block in re.findall(r'<(?:a|div)[^>]*data-hook="tile".*?</(?:a|div)>', html, re.S):
        out.append(
            {
                "href": (re.search(r'href="([^"]*)"', block) or [None, ""])[1],
                "value": re.search(r'tile-value">(.*?)<', block, re.S).group(1).strip(),
                "label": re.search(r'tile-label">(.*?)<', block, re.S).group(1).strip(),
                "status": re.search(r"tile tile-(\w+)", block).group(1),
            }
        )
    return out


def test_two_waiting_briefs_and_one_signed_read_the_same_in_sentence_and_tile(tmp_path):
    runs = {"waiting": 2, "signed": 1}
    topic = make_topic(
        tmp_path, "compliance-brief", waiting=lambda: runs["waiting"], title="Compliance brief"
    )
    page = home(tmp_path, topic)
    assert sentence_of(page) == "2 briefs are waiting for a reviewer."
    assert tiles_of(page) == [
        {
            "href": "/compliance-brief/",
            "value": "2",
            "label": "Compliance brief",
            "status": "needs_person",
        }
    ]


def test_changing_the_waiting_count_changes_the_sentence_and_the_tile_together(tmp_path):
    held = {"count": 2}
    topic = make_topic(tmp_path, "compliance-brief", waiting=lambda: held["count"])
    for count, sentence in (
        (2, "2 briefs are waiting for a reviewer."),
        (1, "1 brief is waiting for a reviewer."),
        (0, "No brief is waiting for a reviewer."),
        (7, "7 briefs are waiting for a reviewer."),
    ):
        held["count"] = count
        page = home(tmp_path, topic)
        assert sentence_of(page) == sentence
        assert [t["value"] for t in tiles_of(page)] == [str(count)]


def test_with_nothing_waiting_the_sentence_says_so_and_the_tile_is_not_flagged(tmp_path):
    page = home(tmp_path, make_topic(tmp_path, "compliance-brief", waiting=lambda: 0))
    assert sentence_of(page) == "No brief is waiting for a reviewer."
    assert [t["status"] for t in tiles_of(page)] == ["normal"]


def test_each_workflow_is_a_tile_with_its_own_count_linking_to_its_list(tmp_path):
    topics = [
        make_topic(tmp_path, "kyc-onboarding", waiting=lambda: 3, noun="case", title="KYC"),
        make_topic(tmp_path, "compliance-brief", waiting=lambda: 2, title="Compliance brief"),
        make_topic(tmp_path, "monitoring", waiting=lambda: 0, noun="alert", title="Monitoring"),
    ]
    page = home(tmp_path, *topics)
    assert sentence_of(page) == "3 cases and 2 briefs are waiting for a reviewer."
    assert tiles_of(page) == [
        {"href": "/kyc-onboarding/", "value": "3", "label": "KYC", "status": "needs_person"},
        {
            "href": "/compliance-brief/",
            "value": "2",
            "label": "Compliance brief",
            "status": "needs_person",
        },
        {"href": "/monitoring/", "value": "0", "label": "Monitoring", "status": "normal"},
    ]


def test_workflows_with_the_same_noun_are_added_in_the_sentence(tmp_path):
    topics = [
        make_topic(tmp_path, "one", waiting=lambda: 2),
        make_topic(tmp_path, "two", waiting=lambda: 1),
    ]
    assert sentence_of(home(tmp_path, *topics)) == "3 briefs are waiting for a reviewer."


def test_nothing_waiting_across_several_nouns_says_nothing_is_waiting(tmp_path):
    topics = [
        make_topic(tmp_path, "one", waiting=lambda: 0),
        make_topic(tmp_path, "two", waiting=lambda: 0, noun="case"),
    ]
    assert sentence_of(home(tmp_path, *topics)) == "Nothing is waiting for a reviewer."


def test_a_workflow_that_cannot_say_what_waits_is_named_in_words_and_never_counted_as_nought(
    tmp_path,
):
    topics = [
        make_topic(tmp_path, "compliance-brief", waiting=lambda: None, title="Compliance brief"),
        make_topic(tmp_path, "monitoring", waiting=lambda: 2, noun="alert", title="Monitoring"),
    ]
    page = home(tmp_path, *topics)
    assert sentence_of(page) == (
        "2 alerts are waiting for a reviewer. Compliance brief cannot say what is waiting."
    )
    unavailable = tiles_of(page)[0]
    assert unavailable["value"] == "Not available" and unavailable["status"] == "normal"


def test_with_only_unavailable_workflows_the_sentence_names_them_and_claims_no_count(tmp_path):
    topic = make_topic(tmp_path, "compliance-brief", waiting=lambda: None, title="Compliance brief")
    assert sentence_of(home(tmp_path, topic)) == "Compliance brief cannot say what is waiting."


def test_more_workflows_than_tiles_gives_one_total_tile_and_every_workflow_in_the_list(tmp_path):
    topics = [make_topic(tmp_path, f"flow-{i}", waiting=lambda i=i: i) for i in range(4)]
    page = home(tmp_path, *topics)
    assert sentence_of(page) == "6 briefs are waiting for a reviewer."
    assert page.count('data-hook="tile"') == 1
    assert tiles_of(page)[0]["value"] == "6"
    for i in range(4):
        assert f'href="/flow-{i}/"' in page


def test_the_page_has_one_sentence_at_most_three_tiles_one_exhibit_and_names_every_workflow(
    tmp_path,
):
    topics = [make_topic(tmp_path, f"flow-{i}", waiting=lambda i=i: i) for i in range(MAX_TILES)]
    page = home(tmp_path, *topics)
    assert page.count('data-hook="sentence"') == 1
    assert page.count('data-hook="tile"') == MAX_TILES
    assert page.count('data-hook="exhibit"') == 1
    for topic in topics:
        assert topic.summary in page


def test_the_home_page_says_nothing_about_what_has_been_built(tmp_path):
    topics = [make_topic(tmp_path, "compliance-brief", waiting=lambda: 2)]
    page = home(tmp_path, *topics)
    visible = re.sub(r"<[^>]+>", " ", page)
    assert not re.search(r"\bbuilt\b", visible, re.I)
    assert "topics are" not in visible and "topic is" not in visible


def test_a_topic_that_gives_no_count_waits_for_nothing(tmp_path):
    bare = TopicPlugin(
        name="plain",
        title="Plain",
        summary="No count given.",
        prefix="/plain",
        routes=[],
        templates_dir=tmp_path,
    )
    assert bare.waiting() == 0
    assert bare.list_href == "/plain/"
    assert sentence_of(home(tmp_path, bare)) == "No item is waiting for a reviewer."


def test_summarise_home_builds_the_sentence_and_the_tiles_from_the_same_entries(tmp_path):
    summary = summarise_home(
        [
            make_topic(tmp_path, "a", waiting=lambda: 2, title="A"),
            make_topic(tmp_path, "b", waiting=lambda: 0, title="B"),
        ]
    )
    assert isinstance(summary, HomeSummary)
    assert summary.entries == (
        HomeEntry(title="A", href="/a/", noun="brief", waiting=2),
        HomeEntry(title="B", href="/b/", noun="brief", waiting=0),
    )
    answer = summary.answer()
    assert answer.sentence == "2 briefs are waiting for a reviewer."
    assert [t.value for t in answer.tiles] == [str(e.waiting) for e in summary.entries]
    assert all(isinstance(t, Tile) for t in answer.tiles)
    assert answer.tiles[0].href == "/a/" and answer.tiles[0].status == "needs_person"


def test_a_negative_count_is_refused_in_words(tmp_path):
    with pytest.raises(ValueError, match="cannot be below nought"):
        summarise_home([make_topic(tmp_path, "a", waiting=lambda: -1, title="A")])
