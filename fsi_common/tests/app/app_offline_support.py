"""A small topic for the offline exporter's tests: links, a redirect, a CSV, a form and ids."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from fsi_common.app import Answer, AppConfig, Tile, TopicPlugin, create_app, render
from fsi_common.app.session import SessionCodec
from fsi_common.records import Person

RUN = "3f2b8c1e-9a4d-4e7b-8c55-0d1f6a7b9e21"
SECRET = b"offline-test-secret"
REVIEWER = Person(name="Dana Whitfield", role="Head of Compliance")
STYLE = "body { margin: 0; }\n.mark { color: #1b2430; }\n"

INDEX = """{% extends "base.html" %}
{% import "macros.html" as ui %}
{% block styles %}<link rel="stylesheet" href="/toy/static/toy.css">{% endblock %}
{% block main %}
{{ ui.answer(answer) }}
<div class="exhibit" data-hook="exhibit">
  <a href="/toy/second?x=1" title="Open the second page">Second</a>
  <a href="/toy/old" title="Open the old address">Old</a>
  <a href="/toy/runs/{{ run }}" title="Open the run">Run</a>
  <a href="/toy/table.csv" title="Download the rows">Export CSV</a>
  <a href="#note" title="Go to the note">To the note</a>
  <form method="post" action="/toy/post" id="form-one">
    <label for="note">Note</label>
    <textarea id="note" name="note" aria-describedby="hint"></textarea>
    <p id="hint">Say what you think.</p>
    <button type="submit" title="Send the note">Send</button>
    <input type="submit" value="Go" title="Go">
    <button type="button" title="Plain button">Not a submit</button>
  </form>
  {{ extra|safe }}
</div>
{% endblock %}
"""

SECOND = """{% extends "base.html" %}
{% import "macros.html" as ui %}
{% block styles %}<link rel="stylesheet" href="/toy/static/toy.css">{% endblock %}
{% block main %}
{{ ui.answer(answer) }}
<div class="exhibit" data-hook="exhibit">
  <a href="/toy/" title="Back to the first page">First</a>
  <p id="note">The second page has its own note.</p>
  <a href="#note" title="Go to the note">To the note</a>
</div>
{% endblock %}
"""


class Toy:
    """The toy topic, its application, and a client signed in as the reviewer."""

    def __init__(self, root: Path, *, extra: str = "", sheet: str = STYLE) -> None:
        templates = root / "templates"
        (templates / "toy").mkdir(parents=True)
        (templates / "toy" / "index.html").write_text(INDEX)
        (templates / "toy" / "second.html").write_text(SECOND)
        static = root / "static"
        static.mkdir()
        (static / "toy.css").write_text(sheet)
        self.extra = extra
        plugin = TopicPlugin(
            name="toy",
            title="Toy topic",
            summary="A topic made for a test.",
            prefix="/toy",
            routes=[
                Route("/", self.index),
                Route("/second", self.second),
                Route("/old", self.old),
                Route("/runs/{run}", self.second),
                Route("/table.csv", self.table),
                Route("/gone", self.gone),
                Route("/data.json", self.data),
            ],
            templates_dir=templates,
            static_dir=static,
            about=("The toy topic holds invented things.",),
        )
        self.app = create_app(AppConfig(secret=SECRET, topic_folders=()), topics=[plugin])
        self.plugin = plugin

    def client(self) -> TestClient:
        """Return a client signed in as the reviewer that does not follow redirects."""
        cookie = SessionCodec(SECRET).encode(REVIEWER)
        return TestClient(
            self.app, follow_redirects=False, cookies={self.app.state.cookie_name: cookie}
        )

    def index(self, request):
        answer = Answer(sentence="The toy topic has 2 things.", tiles=(Tile("Things", "2"),))
        context = {"answer": answer, "page_title": "Toy", "run": RUN, "extra": self.extra}
        return render(request, "toy/index.html", context)

    def second(self, request):
        answer = Answer(sentence="This is the second toy page.")
        return render(request, "toy/second.html", {"answer": answer, "page_title": "Second"})

    def old(self, request):
        return RedirectResponse("/toy/second?x=1", status_code=307)

    def table(self, request):
        return PlainTextResponse(
            'Thing,Count\r\nwidget,2\r\n"a, b",3\r\n',
            media_type="text/csv",
            headers={"content-disposition": 'attachment; filename="things.csv"'},
        )

    def gone(self, request):
        raise HTTPException(404, "There is no thing numbered 7.")

    def data(self, request):
        return JSONResponse({"a": 1})


class Text(HTMLParser):
    """Collects the text a reader sees in some HTML, with whitespace made single."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._in_body = False

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self._in_body = True
        if tag in {"style", "title", "script"}:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in {"style", "title", "script"}:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_body and not self._skip:
            self.parts.append(data)


def body_text(html: str) -> str:
    """Return the words a page shows, in order, with runs of whitespace made one space."""
    reader = Text()
    reader.feed(html)
    return " ".join(" ".join(reader.parts).split())


def sections_of(html: str) -> dict[str, str]:
    """Return the HTML inside each page section of an offline file, by the section's id."""
    found = {}
    for match in re.finditer(
        r'<div class="offline-page" id="([^"]+)"[^>]*>\n(.*?)\n</div>'
        r'(?=\n<div class="offline-page"|\n</body>)',
        html,
        flags=re.S,
    ):
        found[match.group(1)] = match.group(2)
    return found


def outside_references(html: str) -> list[str]:
    """Return every src, href or url() in a file that does not point inside it.

    An address inside the file starts with ``#`` or is a ``data:`` CSV; anything else is outside.
    """
    out = [m for m in re.findall(r'\s(?:src|srcset|poster|data|action|formaction)="([^"]*)"', html)]
    for value in re.findall(r'\shref="([^"]*)"', html):
        if not (value.startswith("#") or value.startswith("data:text/csv")):
            out.append(value)
    out += re.findall(r"url\(([^)]*)\)", html)
    out += re.findall(r"@import[^;]*;", html)
    out += re.findall(r"https?://[^\s\"'<>)]+", html)
    return [unescape(item) for item in out]
