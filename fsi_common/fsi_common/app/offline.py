"""The offline edition: the application's pages for one run, written into one HTML file.

The pages are rendered by the application itself, through Starlette's test client over the real
routes. Every address a reader can reach from the entry page is fetched, each page becomes one
section of the file, every internal link becomes an anchor inside the file, the style sheets are
inlined, a table's CSV export becomes a ``data:`` address, and every form and button is left out,
because a file has no server and no person to decide, so no control in it could do anything.
Nothing is fetched when the file is opened, and nothing is added to what the served pages say.

Run it with ``python -m fsi_common.app.offline --topic NAME --out FILE``; a topic supplies what to
start through an ``OfflineTopic`` in its ``review_app/offline.py``.
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlsplit

from starlette.applications import Starlette
from starlette.testclient import TestClient

from fsi_common.app.config import REPOSITORY_ROOT, built_topic_folders
from fsi_common.app.topics import _own_copy, _take_package
from fsi_common.records import Person

HOOK_MODULE = "review_app.offline"
DEFAULT_REVIEWER = Person(name="Dana Whitfield", role="Head of Compliance")
REDIRECTS = {301, 302, 303, 307, 308}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}
ID_LISTS = ("aria-labelledby", "aria-describedby", "aria-controls", "headers")
FORBIDDEN_ATTRIBUTES = {"src", "srcset", "data", "poster", "ping", "xlink:href", "formaction"}
FORBIDDEN_TAGS = {"script", "iframe", "object", "embed", "img", "video", "audio", "source", "base"}
DROPPED_TAGS = ("form", "button")
"""Elements the file leaves out with everything inside them: a file cannot record or sign out."""

REPLAY_ENV = {
    "MODEL_BACKEND": "replay",
    "LANGSMITH_TRACING": "false",
    "LANGCHAIN_TRACING_V2": "false",
}

SWITCH_CSS = """
.offline-page { display: none; }
.offline-page:target, .offline-page:has(:target) { display: block; }
body:not(:has(:target)) .offline-page[data-entry] { display: block; }
"""


@contextmanager
def replay_only() -> Iterator[None]:
    """Make every model call in the block come from a recording, and send no trace.

    The repository's settings for the model backend and for tracing are set for the block and put
    back when it ends. ``MODEL_RECORDINGS_DIR`` is left as set, so a test can point the export at
    a folder with nothing in it.
    """
    held = {name: os.environ.get(name) for name in REPLAY_ENV}
    os.environ.update(REPLAY_ENV)
    try:
        yield
    finally:
        for name, value in held.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class OfflineExportError(RuntimeError):
    """The pages could not be written into one self-contained file; the message says why."""


@dataclass(frozen=True)
class OfflineTopic:
    """What a topic gives the exporter: its name, its application and how to start a run.

    ``build_app`` returns the topic's application on replayed model calls. ``seed`` receives a
    client signed in as the reviewer, starts what the pages show, waits until it is ready and
    returns the address the file opens on.
    """

    name: str
    build_app: Callable[[], Starlette]
    seed: Callable[[TestClient], str]


@dataclass(frozen=True)
class SiteExport:
    """The file's text and what went into it."""

    html: str
    addresses: tuple[str, ...]
    csv_files: int
    links: int
    entry: str
    ids: dict[str, str] = field(default_factory=dict)
    titles: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _Target:
    """Where a link inside a page now leads, and the file name for a download."""

    href: str
    download: str | None = None


@dataclass
class _Scan:
    """What one page's HTML holds that the crawl needs."""

    title: str = ""
    styles: list[str] = field(default_factory=list)
    hrefs: list[str] = field(default_factory=list)


class _PageParser(HTMLParser):
    """Reads one page and rewrites its body for the file.

    With ``page_id`` it writes the body with ids made unique, links resolved by ``resolve`` and
    forms and buttons left out; without it, it only collects the title, style sheets and links.
    """

    def __init__(
        self, address: str, page_id: str | None, resolve: Callable[[str], _Target] | None
    ) -> None:
        super().__init__(convert_charrefs=False)
        self.address = address
        self.page_id = page_id
        self.resolve = resolve
        self.scan = _Scan()
        self.out: list[str] = []
        self._in_body = False
        self._in_title = False
        self._dropping: str | None = None
        self._dropped_depth = 0
        self.links = 0

    def _fail(self, message: str) -> OfflineExportError:
        return OfflineExportError(f"The page {self.address} {message}.")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, closed=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, closed=True)

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], *, closed: bool) -> None:
        values = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag == "link" and "stylesheet" in (values.get("rel") or "").split():
            self.scan.styles.append(values.get("href") or "")
        if tag == "body":
            self._in_body = True
            return
        if not self._in_body:
            return
        if self._dropping is not None:
            if tag == self._dropping and not closed:
                self._dropped_depth += 1
            return
        if tag in DROPPED_TAGS:
            if not closed:
                self._dropping, self._dropped_depth = tag, 1
            return
        if tag in FORBIDDEN_TAGS:
            raise self._fail(f"holds a <{tag}>, which would fetch or run something")
        items = self._rewrite(tag, attrs)
        if self.page_id is not None:
            self.out.append(_tag_text(tag, items, closed=closed and tag not in VOID_TAGS))

    def _rewrite(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> list[tuple[str, str | None]]:
        items: list[tuple[str, str | None]] = []
        download: str | None = None
        for name, value in attrs:
            if name in FORBIDDEN_ATTRIBUTES:
                raise self._fail(f"has a {name} attribute on <{tag}>, which points outside it")
            if name == "style" and value and "url(" in value:
                raise self._fail("has a style that fetches with url()")
            if name == "action" and tag == "form":
                continue
            if name == "href":
                if tag != "a":
                    raise self._fail(f"has an href on <{tag}>")
                target = self._link(value or "")
                value, download = target.href, target.download
            elif name == "id" and self.page_id and value:
                value = f"{self.page_id}--{value}"
            elif name == "for" and self.page_id and value:
                value = f"{self.page_id}--{value}"
            elif name in ID_LISTS and self.page_id and value:
                value = " ".join(f"{self.page_id}--{part}" for part in value.split())
            items.append((name, value))
        if download is not None:
            items.append(("download", download))
        return items

    def _link(self, href: str) -> _Target:
        self.links += 1
        if href.startswith("#"):
            if self.page_id is None:
                return _Target(href)
            return _Target(f"#{self.page_id}--{href[1:]}")
        if not href.startswith("/") or href.startswith("//"):
            raise self._fail(f"links to {href}, which is outside the application")
        self.scan.hrefs.append(href)
        if self.resolve is None:
            return _Target(href)
        return self.resolve(href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "body":
            self._in_body = False
            return
        if not self._in_body:
            return
        if self._dropping is not None:
            if tag == self._dropping:
                self._dropped_depth -= 1
                if self._dropped_depth == 0:
                    self._dropping = None
            return
        if tag not in VOID_TAGS and self.page_id is not None:
            self.out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.scan.title += data
        if self._in_body and self.page_id is not None and self._dropping is None:
            self.out.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._in_title:
            self.scan.title += f"&{name};"
        if self._in_body and self.page_id is not None and self._dropping is None:
            self.out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._in_title:
            self.scan.title += f"&#{name};"
        if self._in_body and self.page_id is not None and self._dropping is None:
            self.out.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        return None

    def handle_decl(self, decl: str) -> None:
        return None


def _tag_text(tag: str, items: Sequence[tuple[str, str | None]], *, closed: bool) -> str:
    parts = [tag]
    for name, value in items:
        parts.append(name if value is None else f'{name}="{escape(value, quote=True)}"')
    return f"<{' '.join(parts)}{'/' if closed else ''}>"


def _unescape_title(raw: str) -> str:
    return unescape(" ".join(raw.split()))


def _address(location: str) -> str:
    """Return the path and query of an address, which may be written in full."""
    parts = urlsplit(location)
    return parts.path + (f"?{parts.query}" if parts.query else "")


def _slug(address: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", address.lower()).strip("-")
    return f"page-{text or 'home'}"


class _Crawl:
    """Every page reachable from an entry address, fetched from the application."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.html: dict[str, str] = {}
        self.alias: dict[str, str] = {}
        self.csv: dict[str, tuple[str, str]] = {}
        self.styles: list[str] = []

    def run(self, seeds: Sequence[str]) -> None:
        queue: deque[str] = deque(seeds)
        seen = set(seeds)
        while queue:
            address = queue.popleft()
            found = self._fetch(address)
            for target in found:
                if target not in seen:
                    seen.add(target)
                    queue.append(target)

    def _fetch(self, address: str) -> list[str]:
        response = self.client.get(address)
        if response.status_code in REDIRECTS:
            target = _address(response.headers["location"])
            self.alias[address] = target
            return [target]
        if response.status_code != 200:
            raise OfflineExportError(
                f"The address {address} answered {response.status_code} instead of a page."
            )
        kind = response.headers.get("content-type", "")
        if kind.startswith("text/csv"):
            name = re.search(r'filename="([^"]+)"', response.headers.get("content-disposition", ""))
            self.csv[address] = (response.content.decode("utf-8"), name.group(1) if name else "")
            return []
        if not kind.startswith("text/html"):
            raise OfflineExportError(f"The address {address} answered {kind}, which is not a page.")
        self.html[address] = response.text
        parser = _PageParser(address, None, None)
        parser.feed(response.text)
        parser.close()
        for style in parser.scan.styles:
            if style not in self.styles:
                self.styles.append(style)
        return [_address(h) for h in dict.fromkeys(parser.scan.hrefs)]


def _inline_styles(client: TestClient, styles: Sequence[str]) -> str:
    sheets = []
    for address in styles:
        response = client.get(address)
        if response.status_code != 200:
            raise OfflineExportError(f"The style sheet {address} answered {response.status_code}.")
        text = response.text
        if "url(" in text or "@import" in text:
            raise OfflineExportError(f"The style sheet {address} fetches something with url().")
        sheets.append(text.strip())
    return "\n".join(sheets)


def _final(alias: dict[str, str], address: str) -> str:
    seen = {address}
    while address in alias:
        address = alias[address]
        if address in seen:
            raise OfflineExportError(f"The address {address} redirects round in a circle.")
        seen.add(address)
    return address


def export_pages(
    app: Starlette, prepare: Callable[[TestClient], str], *, reviewer: Person = DEFAULT_REVIEWER
) -> SiteExport:
    """Write the application's pages, as a signed-in reviewer sees them, into one file's text.

    Args:
        app: The application, on replayed model calls.
        prepare: Receives a client signed in as ``reviewer``, starts what the pages show, waits
            until it is ready and returns the address the file opens on.
        reviewer: The person the pages show as signed in.

    Returns:
        The file's text and what went into it.

    Raises:
        OfflineExportError: If an address does not answer with a page, a link leaves the
            application, a page would fetch or run something, or the text holds an identifier
            that changes on every run.
    """
    cookie = app.state.sessions.encode(reviewer)
    client = TestClient(app, follow_redirects=False, cookies={app.state.cookie_name: cookie})
    entry = prepare(client)
    crawl = _Crawl(client)
    crawl.run([entry, "/"])
    final = {a: _final(crawl.alias, a) for a in {*crawl.html, *crawl.alias}}
    entry = final[entry]
    pages = [entry, *sorted(set(final.values()) - {entry})]
    stable = _stable_names(pages)
    ids = {address: _slug(stable(address)) for address in pages}
    _check_unique(ids)
    links = 0

    def resolver(source: str) -> Callable[[str], _Target]:
        def resolve(href: str) -> _Target:
            address = _address(href)
            if address in crawl.csv:
                text, name = crawl.csv[address]
                return _Target("data:text/csv;charset=utf-8," + quote(text, safe=""), name or None)
            found = final.get(address) or _final(crawl.alias, address)
            if found not in ids:
                raise OfflineExportError(f"The page {source} links to {href}, which is not in it.")
            return _Target(f"#{ids[found]}")

        return resolve

    sections, titles = [], {}
    for address in pages:
        parser = _PageParser(address, ids[address], resolver(address))
        parser.feed(crawl.html[address])
        parser.close()
        links += parser.links
        titles[address] = _unescape_title(parser.scan.title)
        marker = " data-entry" if address == entry else ""
        body = "".join(parser.out).strip("\n")
        sections.append(f'<div class="offline-page" id="{ids[address]}"{marker}>\n{body}\n</div>')
    css = _inline_styles(client, crawl.styles)
    title = escape(titles[entry])
    html = (
        '<!doctype html>\n<html lang="en-GB">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n<style>\n{css}\n{SWITCH_CSS.strip()}\n</style>\n</head>\n<body>\n"
        + "\n".join(sections)
        + "\n</body>\n</html>\n"
    )
    leftover = UUID.search(html)
    if leftover:
        raise OfflineExportError(
            f"The file holds {leftover.group(0)}, an identifier that changes on every run, so "
            "two exports would differ."
        )
    return SiteExport(
        html=html,
        addresses=tuple(pages),
        csv_files=len(crawl.csv),
        links=links,
        entry=entry,
        ids=dict(ids),
        titles=titles,
    )


def _stable_names(pages: Sequence[str]) -> Callable[[str], str]:
    """Return a function that replaces each run identifier in an address by ``run-N``."""
    order: dict[str, str] = {}
    for address in pages:
        for found in UUID.findall(address):
            order.setdefault(found, f"run-{len(order) + 1}")

    def stable(address: str) -> str:
        return UUID.sub(lambda m: order[m.group(0)], address)

    return stable


def _check_unique(ids: dict[str, str]) -> None:
    seen: dict[str, str] = {}
    for address, page_id in ids.items():
        if page_id in seen:
            raise OfflineExportError(
                f"The addresses {seen[page_id]} and {address} would share the anchor {page_id}."
            )
        seen[page_id] = address


def load_hook(folder: Path) -> OfflineTopic:
    """Import one topic folder's ``review_app.offline`` and return its ``HOOK``.

    The package is loaded as the shell loads a plug-in: a topic other than the one already
    imported gets its own copy of ``review_app``, dropped afterwards, so a hook imports what it
    needs at the top of its module.

    Args:
        folder: The topic folder.

    Returns:
        The topic's hook.

    Raises:
        OfflineExportError: If the folder has no hook, importing it fails, or it exports no HOOK.
    """
    folder = folder.resolve()
    if not (folder / "review_app" / "offline.py").is_file():
        raise OfflineExportError(
            f"{folder} has no review_app/offline.py, so it has no offline file."
        )
    shared = _own_copy(folder)
    held = {} if shared else _take_package()
    sys.path.insert(0, str(folder))
    try:
        with replay_only():
            module = importlib.import_module(HOOK_MODULE)
    except (ImportError, SyntaxError) as exc:
        raise OfflineExportError(f"The hook in {folder} could not be imported: {exc}") from exc
    finally:
        sys.path.remove(str(folder))
        if not shared:
            _take_package()
            sys.modules.update(held)
    hook = getattr(module, "HOOK", None)
    if not isinstance(hook, OfflineTopic):
        raise OfflineExportError(
            f"{folder}/review_app/offline.py exports no HOOK of the right type."
        )
    return hook


def write_topic(
    hook: OfflineTopic, out: Path, *, reviewer: Person = DEFAULT_REVIEWER
) -> SiteExport:
    """Write one topic's offline file.

    Args:
        hook: The topic's hook.
        out: The file to write.
        reviewer: The person the pages show as signed in.

    Returns:
        What went into the file.

    Raises:
        OfflineExportError: As ``export_pages``.
    """
    with replay_only():
        exported = export_pages(hook.build_app(), hook.seed, reviewer=reviewer)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(exported.html, encoding="utf-8")
    return exported


def main(argv: Sequence[str] | None = None) -> int:
    """Write a topic's offline file: ``--topic NAME --out FILE``.

    Args:
        argv: The arguments; the process's own when absent.

    Returns:
        0 when the file was written, 1 when it could not be, with the reason on standard error.
    """
    parser = argparse.ArgumentParser(prog="python -m fsi_common.app.offline", description=__doc__)
    parser.add_argument(
        "--topic", required=True, help="the topic's name, for example compliance-brief"
    )
    parser.add_argument("--out", required=True, type=Path, help="the HTML file to write")
    parser.add_argument("--reviewer-name", default=DEFAULT_REVIEWER.name)
    parser.add_argument("--reviewer-role", default=DEFAULT_REVIEWER.role)
    args = parser.parse_args(argv)
    try:
        reviewer = Person(name=args.reviewer_name, role=args.reviewer_role)
        hooks = [
            load_hook(f)
            for f in built_topic_folders(REPOSITORY_ROOT)
            if (f / "review_app" / "offline.py").is_file()
        ]
        chosen = [h for h in hooks if h.name == args.topic]
        if not chosen:
            names = ", ".join(h.name for h in hooks) or "none"
            raise OfflineExportError(
                f"There is no offline topic '{args.topic}'; there is: {names}."
            )
        done = write_topic(chosen[0], args.out, reviewer=reviewer)
    except (OfflineExportError, ValueError) as exc:
        print(f"The offline file was not written. {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {args.out}: {len(done.addresses)} pages, {done.csv_files} CSV files.")
    return 0


if __name__ == "__main__":
    # Run as a script this module is ``__main__``, whose OfflineTopic is not the one a topic's hook
    # builds, so the work is done by the module under its own name.
    from fsi_common.app.offline import main as _main

    raise SystemExit(_main())
