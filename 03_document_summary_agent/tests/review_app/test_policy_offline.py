"""The offline file opens every policy page, with nothing in it that needs a server or a person."""

from __future__ import annotations

import dataclasses
import re

import pytest
from policy_pages_support import (
    BASE,
    LEFT_OUT_COMMANDS,
    LEFT_OUT_REASON,
    make_app,
    write_fake,
    write_left_out,
)
from review_fakes import FakeRuns

from fsi_common.app.offline import export_pages
from review_app import offline
from review_app.context import Services
from review_app.plugin import build_plugin
from review_app.routes_policies import BUNDLES_ENV, pages_link


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    bundle, root = write_fake(tmp_path_factory.mktemp("offline"))
    client, _ = make_app(root)
    export = export_pages(client.app, lambda _client: BASE)
    return bundle, root, export


def obligation_addresses(bundle):
    return [
        f"{BASE}/obligations/{o.obligation_id.replace(' ', '/', 1)}"
        for o in bundle.obligation_register.obligations
        if o.applies is True
    ]


def test_the_file_holds_every_policy_page_reached_from_the_picture(made):
    bundle, _, export = made
    wanted = [
        BASE,
        f"{BASE}/register",
        f"{BASE}/clauses",
        f"{BASE}/graph",
        f"{BASE}/gap-report",
        f"{BASE}/measures",
        *obligation_addresses(bundle),
    ]
    assert len(wanted) == 225
    missing = [a for a in wanted if a not in export.addresses]
    assert missing == []
    assert export.entry == BASE


def test_the_register_and_the_clauses_are_in_the_file_as_csv_downloads(made):
    _, _, export = made
    assert export.csv_files >= 2
    assert export.html.count('download="register.csv"') >= 1
    assert export.html.count('download="clauses.csv"') >= 1


def test_the_file_has_no_form_no_button_no_script_and_nothing_that_points_outside_it(made):
    _, _, export = made
    text = export.html
    for part in ("<form", "<button", "<textarea", "<script", "<img", "<link", "@import", "url("):
        assert part not in text, part
    for href in re.findall(r'\shref="([^"]*)"', text):
        assert href.startswith("#") or href.startswith("data:text/csv"), href
    assert "Sign out" not in text and "Record my decision" not in text
    assert re.search(r"https?://", text) is None


def test_every_policy_page_of_the_file_shows_the_demo_tag_and_its_sentence(made):
    _, _, export = made
    assert export.html.count('data-hook="demo-tag"') == len(export.addresses)
    assert export.html.count('data-hook="sentence"') == len(export.addresses)


def test_a_picture_row_opens_its_assessment_inside_the_file(made):
    bundle, _, export = made
    target = f"{BASE}/obligations/DORA/art:30/2"
    page_id = export.ids[target]
    assert f'href="#{page_id}"' in export.html
    assert "DORA Article 30(2) is partly covered by the documents in force." in export.html


def test_the_same_bundle_exports_to_the_same_bytes(made):
    _, root, export = made
    client, _ = make_app(root)
    again = export_pages(client.app, lambda _client: BASE)
    assert again.html == export.html


def test_the_policy_pages_are_given_to_a_plug_in_once_and_the_start_page_can_ask_for_them(
    made, monkeypatch
):
    _, root, _ = made
    monkeypatch.setenv(BUNDLES_ENV, str(root))
    services = Services(runs=lambda: FakeRuns())
    listed = build_plugin(services)
    assert [getattr(r, "path", "") for r in listed.routes].count(offline.POLICY_PICTURE) == 1
    assert offline.with_policy_pages(listed, services) is listed
    assert listed.template_globals["policy_pages"]() == BASE
    bare = dataclasses.replace(
        listed,
        routes=[r for r in listed.routes if "/policies/" not in getattr(r, "path", "")],
        template_globals={k: v for k, v in listed.template_globals.items() if k != "policy_pages"},
    )
    with_pages = offline.with_policy_pages(bare, services)
    paths = [getattr(r, "path", "") for r in with_pages.routes]
    assert paths.count(offline.POLICY_PICTURE) == 1
    assert offline.with_policy_pages(with_pages, services) is with_pages
    assert with_pages.template_globals["policy_pages"]() == BASE
    assert "policy_pages" not in bare.template_globals


def test_the_start_pages_link_is_none_when_no_bundle_is_held(tmp_path):
    assert pages_link(Services(runs=lambda: FakeRuns()), tmp_path)() is None
    assert pages_link(Services(runs=lambda: FakeRuns()), tmp_path / "missing")() is None


def test_the_file_of_a_run_with_a_regulation_left_out_says_so_once_and_holds_nothing_of_it(
    tmp_path,
):
    bundle, root = write_left_out(tmp_path)
    client, _ = make_app(root)
    export = export_pages(client.app, lambda _client: BASE)
    text = export.html
    line = f"SS1/23 is not included here: {LEFT_OUT_REASON}. To include it:"
    assert text.count(line) == 1
    for command in LEFT_OUT_COMMANDS:
        assert text.count(command) == 1
    outside = text.replace(line, "").replace(LEFT_OUT_COMMANDS[1], "")
    assert "SS1/23" not in outside and "SS1-23" not in outside
    assert f"{BASE}/obligations/SS1-23/prin:5.1/a" not in export.addresses
