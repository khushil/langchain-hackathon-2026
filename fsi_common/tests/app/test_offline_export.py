"""The offline exporter: one self-contained file from the pages the application serves."""

from __future__ import annotations

import re
import urllib.parse

import pytest
from app_offline_support import (
    REVIEWER,
    RUN,
    Toy,
    body_text,
    outside_references,
    sections_of,
)

from fsi_common.app.offline import (
    OfflineExportError,
    OfflineTopic,
    SiteExport,
    export_pages,
    load_hook,
    main,
)
from fsi_common.app.testing import free_port  # noqa: F401  (kept so the module is importable alone)


def entry_toy(client) -> str:
    return "/toy/"


@pytest.fixture()
def toy(tmp_path):
    return Toy(tmp_path)


@pytest.fixture()
def exported(toy) -> SiteExport:
    return export_pages(toy.app, entry_toy, reviewer=REVIEWER)


def test_every_page_reached_from_the_entry_is_one_section_of_the_file(toy, exported):
    sections = sections_of(exported.html)
    assert sorted(sections) == sorted(
        [
            "page-toy",
            "page-home",
            "page-about",
            "page-toy-second-x-1",
            "page-toy-runs-run-1",
        ]
    )
    assert len(exported.addresses) == len(sections) == 5
    assert exported.entry == "/toy/"
    assert exported.addresses[0] == "/toy/"


def test_the_entry_page_is_the_one_marked_to_open_first(exported):
    marked = re.findall(r'<div class="offline-page" id="([^"]+)" data-entry>', exported.html)
    assert marked == ["page-toy"]


def test_each_section_shows_the_words_the_server_shows(toy, exported):
    client = toy.client()
    sections = sections_of(exported.html)
    served = {
        "page-toy": "/toy/",
        "page-home": "/",
        "page-about": "/about",
        "page-toy-second-x-1": "/toy/second?x=1",
        "page-toy-runs-run-1": f"/toy/runs/{RUN}",
    }
    for page_id, address in served.items():
        wrapped = f"<html><body>{sections[page_id]}</body></html>"
        served_html = client.get(address).text
        controls = re.sub(r"<(form|button)\b.*?</\1>", "", served_html, flags=re.S)
        assert body_text(wrapped) == body_text(controls), address


def test_nothing_is_added_that_the_served_pages_do_not_say(exported):
    words = body_text(exported.html).lower()
    for note in ("offline", "snapshot", "exported", "no network", "recorded"):
        assert note not in words


def test_every_link_leads_to_a_section_or_is_a_csv_download(exported):
    sections = sections_of(exported.html)
    links = re.findall(r'<a [^>]*href="([^"]*)"', exported.html)
    assert links
    for href in links:
        if href.startswith("data:text/csv"):
            continue
        assert href.startswith("#"), href
        assert href[1:] in sections or re.search(rf'\bid="{re.escape(href[1:])}"', exported.html), (
            href
        )
    assert exported.links == len(links)


def test_nothing_in_the_file_points_outside_it(exported):
    assert outside_references(exported.html) == []


def test_ids_are_unique_in_the_file_and_each_page_keeps_its_own(exported):
    ids = re.findall(r'\bid="([^"]+)"', exported.html)
    assert len(ids) == len(set(ids))
    assert "page-toy--note" in ids and "page-toy-second-x-1--note" in ids
    assert 'for="page-toy--loose"' in exported.html and 'id="page-toy--loose"' in exported.html
    assert 'aria-describedby="page-toy--hint"' in exported.html
    assert 'href="#page-toy--note"' in exported.html


def test_the_link_to_an_old_address_leads_to_the_page_it_redirects_to(exported):
    assert 'href="#page-toy-second-x-1" title="Open the old address"' in exported.html


def test_the_run_identifier_is_named_in_order_not_kept(exported):
    assert RUN not in exported.html
    assert 'title="Open the run"' in exported.html
    assert 'href="#page-toy-runs-run-1" title="Open the run"' in exported.html


def test_no_form_and_no_button_is_in_the_file_because_none_could_do_anything(exported):
    html = exported.html
    for part in ("<form", "<button", "<textarea", 'type="submit"'):
        assert part not in html, part
    assert not re.search(r"<[a-z][^>]*\sdisabled", html)
    assert "/toy/post" not in html and "/signout" not in html and "Sign out" not in html
    assert "Say it in the form" not in html  # the form's own words went with it
    assert 'title="Open the second page"' in html  # the links beside the form stay


def test_a_csv_export_becomes_a_download_holding_the_same_rows(toy, exported):
    served = toy.client().get("/toy/table.csv").content.decode("utf-8")
    link = re.search(
        r'<a [^>]*href="(data:text/csv[^"]*)"[^>]*download="things.csv"', exported.html
    )
    assert link, "the CSV link has no data address and file name"
    body = urllib.parse.unquote(link.group(1).split(",", 1)[1])
    assert body == served == 'Thing,Count\r\nwidget,2\r\n"a, b",3\r\n'
    assert exported.csv_files == 1


def test_the_style_sheets_are_inlined_in_the_order_the_pages_name_them(exported):
    head = exported.html.split("</head>")[0]
    assert head.count("<style>") == 1 and "<link" not in exported.html
    assert head.index("--ink:") < head.index(".mark { color")
    assert ".offline-page:target" in head


def test_two_exports_of_the_same_pages_are_the_same_bytes(tmp_path):
    first = export_pages(Toy(tmp_path / "a").app, entry_toy, reviewer=REVIEWER)
    second = export_pages(Toy(tmp_path / "b").app, entry_toy, reviewer=REVIEWER)
    assert first.html == second.html


def test_the_person_shown_is_the_reviewer_given(toy):
    other = REVIEWER.model_copy(update={"name": "Priya Raman", "role": "Compliance officer"})
    done = export_pages(toy.app, entry_toy, reviewer=other)
    assert "Priya Raman, Compliance officer" in done.html
    assert "Dana Whitfield" not in done.html


# Planted faults: each one must stop the export, saying which page and why.


@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        ('<a href="https://example.org/x" title="Out">Out</a>', "outside the application"),
        ('<a href="//example.org/x" title="Out">Out</a>', "outside the application"),
        ('<a href="relative.html" title="Out">Out</a>', "outside the application"),
        ('<img src="/static/x.png" alt="x">', "holds a <img>"),
        ("<script>alert(1)</script>", "holds a <script>"),
        ('<iframe src="/toy/second"></iframe>', "holds a <iframe>"),
        ('<p style="background: url(/x.png)">x</p>', "style that fetches"),
        ('<link rel="stylesheet" href="/static/app.css">', "href on <link>"),
        ('<a href="/toy/gone" title="Gone">Gone</a>', "answered 404"),
        ('<a href="/toy/data.json" title="Data">Data</a>', "application/json"),
    ],
)
def test_a_page_that_would_fetch_run_or_lead_nowhere_stops_the_export(tmp_path, extra, reason):
    toy = Toy(tmp_path, extra=extra)
    with pytest.raises(OfflineExportError, match=re.escape(reason)):
        export_pages(toy.app, entry_toy, reviewer=REVIEWER)


def test_a_missing_page_is_named_with_its_address_and_status(tmp_path):
    toy = Toy(tmp_path, extra='<a href="/toy/gone" title="Gone">Gone</a>')
    with pytest.raises(OfflineExportError, match=r"/toy/gone answered 404"):
        export_pages(toy.app, entry_toy, reviewer=REVIEWER)


def test_a_style_sheet_that_fetches_stops_the_export(tmp_path):
    toy = Toy(tmp_path, sheet="body { background: url(/x.png); }")
    with pytest.raises(OfflineExportError, match=r"style sheet /toy/static/toy.css|fetches"):
        export_pages(toy.app, entry_toy, reviewer=REVIEWER)


def test_an_identifier_that_changes_every_run_in_the_text_stops_the_export(tmp_path):
    toy = Toy(tmp_path, extra=f"<p>Run {RUN} is shown.</p>")
    with pytest.raises(OfflineExportError, match="changes on every run"):
        export_pages(toy.app, entry_toy, reviewer=REVIEWER)


def test_an_entry_that_does_not_answer_stops_the_export(toy):
    with pytest.raises(OfflineExportError, match=r"/toy/gone answered 404"):
        export_pages(toy.app, lambda client: "/toy/gone", reviewer=REVIEWER)


# The command and the hook loader.


def test_a_folder_without_a_hook_is_named(tmp_path):
    with pytest.raises(OfflineExportError, match="has no review_app/offline.py"):
        load_hook(tmp_path)


def test_a_hook_that_exports_the_wrong_thing_is_named(tmp_path):
    package = tmp_path / "topic" / "review_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Wrong."""\n')
    (package / "offline.py").write_text("HOOK = 3\n")
    with pytest.raises(OfflineExportError, match="exports no HOOK of the right type"):
        load_hook(tmp_path / "topic")


def test_a_hook_that_cannot_be_imported_is_named(tmp_path):
    package = tmp_path / "topic" / "review_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Broken."""\n')
    (package / "offline.py").write_text("import a_module_that_does_not_exist\n")
    with pytest.raises(OfflineExportError, match="could not be imported"):
        load_hook(tmp_path / "topic")


def test_a_good_hook_loads_and_is_an_offline_topic(tmp_path):
    package = tmp_path / "topic" / "review_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Good."""\n')
    (package / "offline.py").write_text(
        "from fsi_common.app.offline import OfflineTopic\n"
        "HOOK = OfflineTopic(name='toy', build_app=lambda: None, seed=lambda client: '/')\n"
    )
    hook = load_hook(tmp_path / "topic")
    assert isinstance(hook, OfflineTopic) and hook.name == "toy"


def test_the_command_names_the_topics_there_are_when_asked_for_another(tmp_path, capsys):
    code = main(["--topic", "no-such-topic", "--out", str(tmp_path / "x.html")])
    assert code == 1
    assert "There is no offline topic 'no-such-topic'" in capsys.readouterr().err
    assert not (tmp_path / "x.html").exists()


def test_the_command_refuses_a_machine_as_the_reviewer(tmp_path, capsys):
    code = main(["--topic", "x", "--out", str(tmp_path / "x.html"), "--reviewer-name", "the model"])
    assert code == 1
    assert "not written" in capsys.readouterr().err
