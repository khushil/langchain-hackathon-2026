"""One real export of the compliance brief on replay, shared by the offline tests of a module."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from starlette.testclient import TestClient

from fsi_common.app.offline import SiteExport, export_pages
from review_app.offline import HOOK

SENTENCE = re.compile(r'data-hook="sentence">(.*?)</h1>', re.S)


@dataclass
class RealExport:
    """The export, the client that served its pages, and the file it was written to."""

    export: SiteExport
    client: TestClient
    path: Path

    def served(self, address: str) -> str:
        """Return the page the application serves at an address the export reached."""
        response = self.client.get(address)
        assert response.status_code == 200, address
        return response.text

    def sentence(self, address: str) -> str:
        """Return the answer sentence the application serves at an address."""
        return unescape(SENTENCE.search(self.served(address)).group(1)).strip()


def make_export(path: Path) -> RealExport:
    """Start the application on replay, start a brief on section 7 and export its pages."""
    captured: dict[str, TestClient] = {}

    def prepare(client: TestClient) -> str:
        captured["client"] = client
        return HOOK.seed(client)

    exported = export_pages(HOOK.build_app(), prepare)
    path.write_text(exported.html, encoding="utf-8")
    return RealExport(exported, captured["client"], path)


class _Text(HTMLParser):
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
    reader = _Text()
    reader.feed(html)
    return " ".join(" ".join(reader.parts).split())


def section_html(file_html: str, page_id: str) -> str:
    """Return the HTML of one page's section of the offline file, wrapped as a page."""
    found = re.search(
        rf'<div class="offline-page" id="{re.escape(page_id)}"[^>]*>\n(.*?)\n</div>'
        r'(?=\n<div class="offline-page"|\n</body>)',
        file_html,
        flags=re.S,
    )
    assert found, page_id
    return f"<html><body>{found.group(1)}</body></html>"
