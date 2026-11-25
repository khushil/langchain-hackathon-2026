"""A small act and a small statement in the shapes the publishers use, for the reader's tests.

The Official Journal fixture follows the markup of the two real acts (subdivisions with ids,
paragraphs as divs, points as tables, notes as superscript tags). The supervisory statement fixture
is the word-position output of ``pdftotext -bbox-layout`` for a few pages. Both are built from
parts keyed by id, so a test can leave a part out or repeat one to plant a fault.
"""

from __future__ import annotations

from collections.abc import Iterable
from xml.sax.saxutils import escape

XHTML = "http://www.w3.org/1999/xhtml"


def _p(text: str, css: str = "oj-normal") -> str:
    return f'<p class="{css}">{escape(text)}</p>'


def _point(label: str, body: str) -> str:
    """One point of a list, as the Official Journal sets it: a table of a label and a text."""
    return (
        '<table width="100%" border="0" cellspacing="0" cellpadding="0"><col width="4%"/>'
        f'<tbody><tr><td valign="top"><p class="oj-normal">{escape(label)}</p></td>'
        f'<td valign="top">{body}</td></tr></tbody></table>'
    )


def _note_tag(number: int) -> str:
    """A footnote reference as the Official Journal sets it: the brackets sit outside the tag."""
    return (
        f'<a id="ntc{number}" href="#ntr{number}">(<span class="oj-super oj-note-tag">{number}'
        "</span>)</a>"
    )


def _recital(number: int, text: str) -> tuple[str, str]:
    html = (
        f'<div class="eli-subdivision" id="rct_{number}"><table width="100%"><tbody><tr>'
        f'<td valign="top"><p class="oj-normal">({number})</p></td>'
        f'<td valign="top"><p class="oj-normal">{escape(text)}</p></td></tr></tbody></table></div>'
    )
    return (f"rct_{number}", html)


def _paragraph(article: int, number: int, body: str) -> tuple[str, str]:
    key = f"art_{article}.{number:03d}"
    return (key, f'<div id="{article:03d}.{number:03d}">{body}</div>')


def _article_open(number: int, title: str) -> tuple[str, str]:
    html = (
        f'<div class="eli-subdivision" id="art_{number}">'
        f'<p id="h{number}" class="oj-ti-art">Article {number}</p>'
        f'<div class="eli-title" id="art_{number}.tit_1">'
        f'<p class="oj-sti-art">{escape(title)}</p></div>'
    )
    return (f"art_{number}.open", html)


def _article_close(number: int) -> tuple[str, str]:
    return (f"art_{number}.close", "</div>")


def _chapter_open(roman: str, title: str) -> tuple[str, str]:
    html = (
        f'<div id="cpt_{roman}"><p class="oj-ti-section-1">CHAPTER {roman}</p>'
        f'<div class="eli-title" id="cpt_{roman}.tit_1">'
        f'<p class="oj-ti-section-2">{escape(title)}</p></div>'
    )
    return (f"cpt_{roman}.open", html)


def _section_open(chapter: str, number: str, title: str) -> tuple[str, str]:
    html = (
        f'<div id="cpt_{chapter}.sct_{number}"><p class="oj-ti-section-1">Section {number}</p>'
        f'<div class="eli-title" id="cpt_{chapter}.sct_{number}.tit_1">'
        f'<p class="oj-ti-section-2">{escape(title)}</p></div>'
    )
    return (f"cpt_{chapter}.sct_{number}.open", html)


def _annex_open(roman: str, title: str) -> tuple[str, str]:
    html = (
        f'<div class="eli-container" id="anx_{roman}"><p class="oj-doc-ti">ANNEX {roman}</p>'
        f'<p class="oj-doc-ti">{escape(title)}</p>'
    )
    return (f"anx_{roman}.open", html)


def act_parts() -> list[tuple[str, str]]:
    """Return the sample act as ordered ``(key, html)`` parts; keys name what a test can drop."""
    parts: list[tuple[str, str]] = [
        (
            "header",
            '<table width="100%"><tbody><tr><td><p class="oj-hd-oj">L 1/1</p></td>'
            '<td><p class="oj-hd-lg">EN</p></td></tr></tbody></table>',
        ),
        ("body.open", '<hr class="oj-separator"/><div class="eli-container" id="doc">'),
        (
            "title",
            '<div class="eli-main-title" id="tit_1">'
            + _p("REGULATION (EU) 2099/1 OF THE EUROPEAN PARLIAMENT", "oj-doc-ti")
            + _p("on the sample rules for tests", "oj-doc-ti")
            + "</div>",
        ),
        (
            "pbl.open",
            '<div class="eli-subdivision" id="pbl_1">'
            + _p("THE EUROPEAN PARLIAMENT HAS ADOPTED THIS ACT,"),
        ),
        (
            "cit_1",
            '<div class="eli-subdivision" id="cit_1">'
            + _p("Having regard to the Treaty.")
            + "</div>",
        ),
        (
            "cit_2",
            '<div class="eli-subdivision" id="cit_2">'
            + _p("Whereas the proposal was sent.")
            + "</div>",
        ),
        ("whereas", _p("Whereas:")),
        _recital(1, "Operators need clear rules about sample risk."),
        _recital(2, "Operators shall keep records of sample risk."),
        _recital(3, "The rules apply from a set date."),
        ("pbl.close", "</div>"),
        ("adopted", _p("HAVE ADOPTED THIS REGULATION:")),
        ("enc.open", '<div class="eli-subdivision" id="enc_1">'),
        _chapter_open("I", "General provisions"),
        _article_open(1, "Subject matter"),
        _paragraph(
            1,
            1,
            _p("1.   This Regulation lays down rules on:")
            + _point("(a)", _p("sample risk management;"))
            + _point(
                "(b)",
                _p("incident reporting, including:")
                + _point("(i)", _p("major incidents;"))
                + _point("(ii)", _p("minor incidents.")),
            ),
        ),
        _paragraph(1, 2, _p("2.   It applies to operators that hold a permit.")),
        _article_close(1),
        _article_open(2, "Definitions"),
        ("art_2.lead", _p("For the purposes of this Regulation, the following definitions apply:")),
        ("art_2.pt1", _point("(1)", _p("‘operator’ means a person who runs a sample service;"))),
        ("art_2.pt2", _point("(2)", _p("‘incident’ means an event that harms the service;"))),
        ("art_2.pt3", _point("(3)", _p("‘risk’ means the chance of an incident."))),
        _article_close(2),
        _article_open(3, "Entry into force"),
        ("art_3.body", _p("This Regulation shall apply from 1 January 2099.")),
        _article_close(3),
        ("cpt_I.close", "</div>"),
        _chapter_open("II", "Duties"),
        _section_open("II", "1", "Records"),
        _article_open(4, "Records"),
        _paragraph(
            4,
            1,
            '<p class="oj-normal">1.   Operators shall keep records for five years '
            + _note_tag(1)
            + ".</p>",
        ),
        _paragraph(4, 2, _p("2.   The competent authority may request the records.")),
        _article_close(4),
        ("cpt_II.sct_1.close", "</div>"),
        ("cpt_II.close", "</div>"),
        ("enc.close", "</div>"),
        (
            "fnp",
            '<div class="eli-subdivision" id="fnp_1"><div class="oj-final">'
            + _p("This Regulation shall be binding in its entirety.")
            + _p("For the European Parliament", "oj-signatory")
            + "</div></div>",
        ),
        _annex_open("I", "Sample list"),
        ("anx_I.intro", _p("The list below applies to operators.")),
        ("anx_I.1", _point("1.", _p("Operators of payment services."))),
        (
            "anx_I.2",
            _point(
                "2.",
                _p("Operators of trading venues, in particular:")
                + _point("(a)", _p("exchanges;"))
                + _point("(b)", _p("multilateral venues.")),
            ),
        ),
        ("anx_I.close", "</div>"),
        _annex_open("II", "Grouped list"),
        ("anx_II.g1", _p("Section A. First group", "oj-ti-grseq-1")),
        ("anx_II.g1.1", _point("1.", _p("First entry of the first group."))),
        ("anx_II.g1.2", _point("2.", _p("Second entry of the first group."))),
        ("anx_II.g2", _p("Section B. Second group", "oj-ti-grseq-1")),
        ("anx_II.g2.1", _point("1.", _p("First entry of the second group."))),
        ("anx_II.close", "</div>"),
        ("notes.hr", '<hr class="oj-note"/>'),
        ("note_1", _p("(1) OJ L 1, 1.1.2099, p. 1.", "oj-note")),
        ("body.close", '</div><hr class="oj-doc-end"/>'),
    ]
    return parts


def compose_act(
    *, skip: Iterable[str] = (), repeat: Iterable[str] = (), extra: Iterable[tuple[str, str]] = ()
) -> bytes:
    """Build the sample act's XHTML, leaving parts out or repeating them.

    Args:
        skip: Keys of parts to leave out.
        repeat: Keys of parts to write twice in a row.
        extra: Further ``(key, html)`` parts, appended just before the closing of the body.

    Returns:
        The document as UTF-8 bytes, with the Official Journal's document type declaration.
    """
    skipped = set(skip)
    repeated = set(repeat)
    pieces: list[str] = []
    extras = list(extra)
    for key, html in act_parts():
        if key == "body.close":
            pieces.extend(h for _, h in extras)
        if key in skipped:
            continue
        pieces.append(html)
        if key in repeated:
            pieces.append(html)
    head = (
        '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE html PUBLIC "-//W3C//DTD XHTML//EN" '
        f'"xhtml-strict.dtd"><html xmlns="{XHTML}"><head><title>sample</title></head><body>'
    )
    return (head + "".join(pieces) + "</body></html>").encode("utf-8")


ACT_ANCHORS = [
    "cit:1",
    "cit:2",
    "rct:1",
    "rct:2",
    "rct:3",
    "art:1/1",
    "art:1/2",
    "art:2/lead",
    "art:2/pt1",
    "art:2/pt2",
    "art:2/pt3",
    "art:3",
    "art:4/1",
    "art:4/2",
    "fin:1",
    "anx:I/lead",
    "anx:I/1",
    "anx:I/2",
    "anx:II/s1/1",
    "anx:II/s1/2",
    "anx:II/s2/1",
    "note:1",
]
"""The anchors, in order, that the sample act is read into."""


# ---------------------------------------------------------------------------------------------
# A small supervisory statement, as the word positions that ``pdftotext -bbox-layout`` gives.
# ---------------------------------------------------------------------------------------------

BODY_HEIGHT = 13.4
SUB_HEIGHT = 9.0
NOTE_HEIGHT = 11.1
LABEL_HEIGHT = 7.2
HEADING_HEIGHT = 15.2
CHAPTER_HEIGHT = 26.7
RUNNING_HEAD = "Sample Publisher | Prudential Regulation Authority"


class Line:
    """One line of a page: its words, left edge and height, as the layout tool reports them."""

    def __init__(self, text: str, *, x: float = 49.6, height: float = BODY_HEIGHT) -> None:
        self.text = text
        self.x = x
        self.height = height


class Row:
    """A point whose label and text the layout tool reports as two lines on one row."""

    def __init__(self, label: str, text: str) -> None:
        self.label = Line(label, x=85.0)
        self.text = Line(text, x=105.0)


def body(text: str, *, x: float = 49.6) -> Line:
    return Line(text, x=x)


def heading(text: str) -> Line:
    return Line(text, height=HEADING_HEIGHT)


def chapter(text: str) -> Line:
    return Line(text, height=CHAPTER_HEIGHT)


def footnote(number: int, *lines: str) -> list[Line]:
    """A footnote: its label line and its text lines, all at the foot of the page."""
    out = [Line(str(number), height=LABEL_HEIGHT)]
    out.extend(Line(text, x=66.6, height=NOTE_HEIGHT) for text in lines)
    return out


def _words_xml(line: Line, y: float) -> str:
    words = []
    x = line.x
    for token in line.text.split():
        small = token.startswith("^")
        text = token[1:] if small else token
        height = SUB_HEIGHT if small else line.height
        top = y if not small else y - 2.0
        width = 6.0 * len(text)
        words.append(
            f'<word xMin="{x:.2f}" yMin="{top:.2f}" xMax="{x + width:.2f}" '
            f'yMax="{top + height:.2f}">{escape(text)}</word>'
        )
        x += width + 3.0
    return "".join(words)


def statement_bbox(pages: list[list[Line | Row | list[Line]]]) -> bytes:
    """Build the layout tool's word-position XHTML from pages of lines.

    Args:
        pages: Each page is a list of lines and footnotes; a footnote is a list of its lines. Each
            page gets the running head and a page number first, as the real pages do.

    Returns:
        The XHTML as UTF-8 bytes.
    """
    out = [
        f'<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 '
        f'Transitional//EN" "x.dtd"><html xmlns="{XHTML}"><head><title>SS</title></head><body><doc>'
    ]
    for number, items in enumerate(pages, start=1):
        out.append('<page width="595.32" height="841.92"><flow><block>')
        head = Line(RUNNING_HEAD, height=12.8)
        out.append(
            f'<line xMin="49.6" yMin="49.7" xMax="300" yMax="62.5">{_words_xml(head, 49.7)}</line>'
        )
        tag = Line(f"Page {number}", x=509.4, height=12.8)
        out.append(
            f'<line xMin="509.4" yMin="49.7" xMax="540" yMax="62.5">{_words_xml(tag, 49.7)}</line>'
        )
        out.append("</block></flow>")
        y = 80.0
        foot_y = 690.0
        for item in items:
            if isinstance(item, list):
                for note_line in item:
                    out.append(
                        f'<flow><block><line xMin="{note_line.x}" yMin="{foot_y:.2f}" xMax="500" '
                        f'yMax="{foot_y + note_line.height:.2f}">'
                        f"{_words_xml(note_line, foot_y)}</line>"
                        "</block></flow>"
                    )
                    if note_line.height != LABEL_HEIGHT:
                        foot_y += 11.5
                continue
            if isinstance(item, Row):
                for part in (item.label, item.text):
                    out.append(
                        f'<flow><block><line xMin="{part.x}" yMin="{y:.2f}" xMax="500" '
                        f'yMax="{y + part.height:.2f}">{_words_xml(part, y)}</line></block></flow>'
                    )
                y += BODY_HEIGHT + 4.0
                continue
            out.append(
                f'<flow><block><line xMin="{item.x}" yMin="{y:.2f}" xMax="500" '
                f'yMax="{y + item.height:.2f}">{_words_xml(item, y)}</line></block></flow>'
            )
            y += item.height + 4.0
        out.append("</page>")
    out.append("</doc></body></html>")
    return "".join(out).encode("utf-8")


def sample_statement(*, drop: Iterable[str] = (), repeat: Iterable[str] = ()) -> bytes:
    """Return the sample statement's word positions, leaving lines out or repeating them.

    Args:
        drop: Texts of body lines to leave out (a line is dropped when it starts with a text).
        repeat: Texts of body lines to write twice.

    Returns:
        The XHTML as UTF-8 bytes.
    """
    dropped = tuple(drop)
    repeated = tuple(repeat)
    cover = [
        body("Model risk sample statement"),
        body("April 2026"),
        body("© Sample Publisher 2026"),
    ]
    page_1 = [
        chapter("1. Introduction"),
        body("1.1 This statement sets out expectations for banks’ ^1 sample risk."),
        body("1.2 It applies to firms with approval to use internal models."),
        heading("Implementation"),
        body("1.3. The policy applies from 1 January 2099."),
        footnote(1, "The term banks includes building societies."),
    ]
    page_2 = [
        chapter("2. Background"),
        body("2.1 Firms use models in several ways:"),
        body("i. to price products; and", x=70.0),
        body("ii. to measure risk.", x=70.0),
        chapter("3. Overview of the principles"),
        body("3.1 The board is responsible for the framework."),
        heading("Principle 1 – Identification"),
        body("Firms should keep a model inventory."),
        heading("Principle 2 – Governance"),
        body("The board should approve the policy."),
        body("3.2 The principles are supported by sub-principles."),
    ]
    page_3 = [
        chapter("4. Principles for"),
        chapter("banks"),
        heading("Principle 1 – Identification"),
        body("Firms should keep a model inventory."),
        heading("Principle 1.1 Model definition ^2"),
        body("A formal definition sets the scope of the framework."),
        body("a) Firms should adopt the following definition of a model:", x=85.0),
        body("(i) a quantitative method; and", x=105.0),
        body("(ii) an output of estimates.", x=105.0),
        body("b) Where methods are complex, firms should", x=85.0),
        body("consider the framework, re-", x=105.0),
        body("performed where relevant.", x=105.0),
        body("c) Firms should document the definition.", x=85.0),
        heading("Principle 1.2 Model inventory"),
        body("a) Firms should maintain a complete inventory.", x=85.0),
        heading("Principle 2 – Governance"),
        body("The board should approve the policy."),
        heading("Principle 2.1 Board responsibilities"),
        body("The framework should be led by the board."),
        body("a) The board should set a risk appetite.", x=85.0),
        body("b) The board should receive regular reports.", x=85.0),
        Row("c)", "The board should review the framework."),
        footnote(2, "A model includes expert judgement."),
    ]

    def keep(items: list[Line | Row | list[Line]]) -> list[Line | Row | list[Line]]:
        out: list[Line | Row | list[Line]] = []
        for item in items:
            if isinstance(item, Row):
                out.append(item)
            elif isinstance(item, Line):
                if any(item.text.startswith(t) for t in dropped):
                    continue
                out.append(item)
                if any(item.text.startswith(t) for t in repeated):
                    out.append(item)
            elif f"note:{item[0].text}" not in dropped:
                out.append(item)
        return out

    pages = [[Line(t.text) for t in cover], keep(page_1), keep(page_2), keep(page_3)]
    return statement_bbox(pages)


STATEMENT_ANCHORS = [
    "para:1.1",
    "para:1.2",
    "para:1.3",
    "para:2.1",
    "para:3.1",
    "ovw:1",
    "ovw:2",
    "para:3.2",
    "prin:1",
    "prin:1.1",
    "prin:1.1/a",
    "prin:1.1/b",
    "prin:1.1/c",
    "prin:1.2/a",
    "prin:2",
    "prin:2.1",
    "prin:2.1/a",
    "prin:2.1/b",
    "prin:2.1/c",
    "note:1",
    "note:2",
]
"""The anchors, in order, that the sample statement is read into."""
