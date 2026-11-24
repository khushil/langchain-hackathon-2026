"""The words on every page: rendered text is plain, whole and free of dashes and stray markup.

Set ``PAGE_TEXT_DIR`` to keep each page's text, one file a page, so that an editor's prose checker
can be run over the words a person reads.
"""

from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from review_fakes import FakeRuns, examples_review, section_seven_review
from review_fixtures import DANA, TODAY, make_client
from review_helpers import BASE, RUN, finish, runs_for_every_page, signed_section_seven_run

from fsi_common.examples.data import build_examples
from fsi_common.records import Decision

EX = build_examples()

DASHES = ("\u2014", "\u2013")  # an em dash and an en dash
BLOCKS = {"p", "li", "h1", "h2", "h3", "div", "section", "article", "tr", "dt", "dd", "label"}
ROOT = Path(__file__).resolve().parents[3]
APPLICATION_FILES = (
    ROOT / "03_document_summary_agent" / "review_app",
    ROOT / "03_document_summary_agent" / "tests" / "review_app",
    ROOT / "fsi_common" / "fsi_common" / "app",
    ROOT / "fsi_common" / "tests" / "app",
)


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = [""]
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        if tag in BLOCKS:
            self.lines.append("")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip -= 1
        if tag in BLOCKS:
            self.lines.append("")

    def handle_data(self, data):
        if not self.skip:
            self.lines[-1] += data


def page_text(html: str) -> str:
    """Return what a person reads on a page, one block to a line."""
    parser = _Text()
    parser.feed(html)
    lines = (re.sub(r"\s+", " ", line).strip() for line in parser.lines)
    return "\n".join(line for line in lines if line)


def _pages() -> dict[str, str]:
    """Render every kind of page, with the states that change its words."""
    pages: dict[str, str] = {}
    runs = runs_for_every_page()
    c = make_client(runs)
    for name, path in {
        "start": f"{BASE}/",
        "running": f"{BASE}/runs/run-3",
        "stopped": f"{BASE}/runs/run-4",
        "review": f"{RUN}/review",
        "questions": f"{RUN}/review?tab=questions",
        "signoff": f"{RUN}/review?tab=signoff",
        "facts": f"{RUN}/facts",
        "signed": f"{BASE}/runs/run-2/signed",
        "about": "/about",
        "home": "/",
        "signin": "/signin",
        "unknown": f"{BASE}/runs/none/review",
    }.items():
        pages[name] = c.get(path).text
    carried = FakeRuns()
    carried.add(
        "run-1", "awaiting_review", review=examples_review(earlier={EX.fact_7_1.id: EX.accept_7_1})
    )
    pages["review, carried"] = (
        make_client(carried).get(f"{RUN}/review", params={"fact": EX.fact_7_1.id}).text
    )
    seven = FakeRuns()
    seven.add("run-1", "awaiting_review", review=section_seven_review())
    pages["review, section 7"] = make_client(seven).get(f"{RUN}/review").text
    pages["facts, section 7"] = make_client(seven).get(f"{RUN}/facts").text
    pages["signed, section 7"] = make_client(signed_section_seven_run()).get(f"{RUN}/signed").text
    returned = FakeRuns()
    finish(
        returned,
        "run-1",
        [Decision.on(EX.fact_7_1, outcome="reject", reason="No.", reviewer=DANA, date=TODAY)],
        DANA,
        on=TODAY,
        outcome="returned",
    )
    pages["signed, returned"] = make_client(returned).get(f"{RUN}/signed").text
    return pages


PAGES = _pages()


@pytest.mark.parametrize("name", sorted(PAGES))
def test_the_words_of_each_page_hold_no_dash_and_no_unrendered_markup(name):
    text = page_text(PAGES[name])
    assert text
    for dash in DASHES:
        assert dash not in text, (name, dash)
    for marker in ("{{", "{%", "}}", "%}", "undefined", "TODO", "FIXME"):
        assert marker not in text, (name, marker)
    assert not re.search(r"\bNone\b(?! stated in the paragraph)", text), name


def test_no_file_of_the_application_or_its_tests_holds_a_dash():
    seen = 0
    for folder in APPLICATION_FILES:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".html", ".css"}:
                seen += 1
                text = path.read_text(encoding="utf-8")
                assert not any(d in text for d in DASHES), path
    assert seen > 60


def _keep(pages: dict[str, str]) -> None:
    target = os.environ.get("PAGE_TEXT_DIR")
    if not target:
        return
    folder = Path(target)
    folder.mkdir(parents=True, exist_ok=True)
    for name, html in pages.items():
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        (folder / f"{slug}.md").write_text(page_text(html) + "\n", encoding="utf-8")


def test_the_text_of_each_page_is_kept_for_the_editors_check_when_a_folder_is_named(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PAGE_TEXT_DIR", str(tmp_path))
    _keep(PAGES)
    kept = {p.stem for p in tmp_path.glob("*.md")}
    assert len(kept) == len(PAGES)
    assert "Dana Whitfield" in (tmp_path / "signed.md").read_text(encoding="utf-8")


def test_nothing_is_kept_when_no_folder_is_named(monkeypatch):
    monkeypatch.delenv("PAGE_TEXT_DIR", raising=False)
    _keep(PAGES)


def test_the_text_of_each_page_is_written_where_the_environment_says():
    _keep(PAGES)  # a run that sets PAGE_TEXT_DIR leaves the pages' text there
