"""Read a supervisory statement published as a PDF into numbered paragraphs, principles and points.

The reader works on the word positions that ``pdftotext -bbox-layout`` (poppler) reports, because
a page's text alone cannot tell a footnote marker from a digit, nor a footnote from a paragraph.
Heights separate body text, headings, footnote text and superscript markers; the numbering of the
statement itself (paragraphs 1.1, principles 2.3, points a, b, c) is then checked for gaps and
repeats. Every line of every page is placed in a unit, a heading or a named furniture class, or the
read is refused.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from context.regulations.errors import RegulationFormatError, RegulationToolMissingError
from context.regulations.lists import sequence_gap
from context.regulations.model import Closure, RegulationRead, RegUnit, StructureNode, assemble
from fsi_common.ids import digest_bytes
from fsi_common.records import Source

NS = "{http://www.w3.org/1999/xhtml}"
_RUNNING_HEAD = re.compile(r"\|\s*Prudential Regulation Authority$")
_PAGE_NUMBER = re.compile(r"^Page \d+$")
_CHAPTER = re.compile(r"^(\d+)\.\s+(\S.*)$")
_PRINCIPLE = re.compile(r"^Principle (\d+)\s+[–-]\s+(\S.*)$")
_SUB_PRINCIPLE = re.compile(r"^Principle (\d+)\.(\d+)\s+(\S.*)$")
_PARAGRAPH = re.compile(r"^(\d+)\.(\d+)\.?\s+(\S.*)$")
_POINT = re.compile(r"^([a-z])\)\s+(\S.*)$")
_MARGIN_TOLERANCE = 6.0
_POINT_INDENT = 10.0
_HEADING_RATIO = 1.05
_NOTE_RATIO_LOW, _NOTE_RATIO_HIGH, _MARK_RATIO = 0.7, 0.9, 0.8


@dataclass
class _Line:
    index: int
    page: int
    x: float
    y: float
    height: float
    words: list[tuple[str, float]]

    @property
    def text(self) -> str:
        return " ".join(w for w, _ in self.words)


def find_pdftotext() -> str:
    """Return the path of poppler's ``pdftotext``.

    Returns:
        The program's path.

    Raises:
        RegulationToolMissingError: If the program is not installed.
    """
    program = shutil.which("pdftotext")
    if program is None:
        raise RegulationToolMissingError(
            "The program pdftotext is not installed. It is part of poppler-utils, for example "
            "`apt install poppler-utils`; the supervisory statement cannot be read without it."
        )
    return program


def layout_from_pdf(pdf: bytes) -> bytes:
    """Run poppler's ``pdftotext -bbox-layout`` on a PDF and return its word positions.

    Args:
        pdf: The PDF's bytes.

    Returns:
        The layout as XHTML bytes.

    Raises:
        RegulationToolMissingError: If ``pdftotext`` is not installed.
        RegulationFormatError: If the program cannot read the PDF.
    """
    program = find_pdftotext()
    with tempfile.TemporaryDirectory(prefix="ss-layout-") as folder:
        target = Path(folder) / "statement.pdf"
        target.write_bytes(pdf)
        done = subprocess.run(  # noqa: S603 - a fixed program, the file named by this function
            [program, "-bbox-layout", str(target), "-"], capture_output=True, check=False
        )
    if done.returncode != 0:
        raise RegulationFormatError(
            f"pdftotext could not read the PDF (exit {done.returncode}): "
            f"{done.stderr.decode('utf-8', 'replace').strip()}."
        )
    return done.stdout


def _parse(layout: bytes) -> list[_Line]:
    try:
        root = ET.fromstring(layout)
    except ET.ParseError as exc:
        raise RegulationFormatError(f"The layout is not well-formed XHTML: {exc}.") from exc
    lines: list[_Line] = []
    for page_number, page in enumerate((e for e in root.iter() if e.tag == f"{NS}page"), 1):
        for line in (e for e in page.iter() if e.tag == f"{NS}line"):
            words = [
                (
                    unicodedata.normalize("NFC", "".join(w.itertext())),
                    float(w.get("yMax", "0")) - float(w.get("yMin", "0")),
                )
                for w in line
                if w.tag == f"{NS}word"
            ]
            words = [(t, h) for t, h in words if t.strip()]
            if not words:
                continue
            lines.append(
                _Line(
                    index=len(lines),
                    page=page_number,
                    x=float(line.get("xMin", "0")),
                    y=float(line.get("yMin", "0")),
                    height=max(h for _, h in words),
                    words=words,
                )
            )
    if not lines:
        raise RegulationFormatError("The layout holds no line of text.")
    return _merge_rows(lines)


def _is_running(line: _Line) -> bool:
    return bool(_RUNNING_HEAD.search(line.text) or _PAGE_NUMBER.match(line.text))


def _merge_rows(lines: list[_Line]) -> list[_Line]:
    """Join lines the tool reports separately although they stand on one row of one page.

    A point's label, for example ``f)``, can be reported as its own line apart from its text. Left
    alone it would be read as the tail of the point before. Running heads and page numbers share
    a row on purpose and footnote labels share a row with their text on purpose, so those are left.
    """
    merged: list[_Line] = []
    for line in lines:
        prev = merged[-1] if merged else None
        if (
            prev is not None
            and prev.page == line.page
            and abs(prev.y - line.y) < 1.0
            and abs(prev.height - line.height) < 1.0
            and line.x > prev.x
            and not _is_running(prev)
            and not _is_running(line)
        ):
            prev.words.extend(line.words)
            continue
        merged.append(line)
    for index, line in enumerate(merged):
        line.index = index
    return merged


def _join(lines: list[str]) -> str:
    """Join wrapped lines; a hyphen at a line end joins to the next word without a space."""
    out = ""
    for text in lines:
        if out.endswith("-") and text[:1].islower():
            out += text
        else:
            out = f"{out} {text}" if out else text
    return " ".join(out.split())


@dataclass
class _Unit:
    anchor: str
    kind: str
    label: str
    parents: tuple[str, ...]
    heading: str
    lines: list[_Line] = field(default_factory=list)
    notes: list[int] = field(default_factory=list)


@dataclass
class _State:
    chapter: int = 0
    topic_count: int = 0
    topic: str | None = None
    principle: int = 0
    sub: tuple[int, int] | None = None
    open: _Unit | None = None


class _Reader:
    def __init__(self, lines: list[_Line]) -> None:
        self.lines = lines
        self.claims: dict[int, str] = {}
        self.furniture: Counter[str] = Counter()
        self.units: list[_Unit] = []
        self.structure: list[StructureNode] = []
        self.anchors: set[str] = set()
        self.markers: list[int] = []
        self.labels: list[tuple[int, int, float]] = []
        self.note_lines: list[_Line] = []
        self.paragraphs: dict[int, list[int]] = {}
        self.overview: list[int] = []
        self.principles: list[int] = []
        self.subs: dict[int, list[int]] = {}
        self.points: dict[tuple[int, int], list[str]] = {}
        self.chapters: list[int] = []

    def claim(self, line: _Line, what: str, *, furniture: bool = False) -> None:
        if line.index in self.claims:
            raise RegulationFormatError(f"A line is placed twice: {line.text[:60]!r}.")
        self.claims[line.index] = what
        if furniture:
            self.furniture[what] += 1

    def start(self, state: _State, unit: _Unit) -> None:
        if unit.anchor in self.anchors:
            raise RegulationFormatError(f"The unit {unit.anchor} appears twice in the statement.")
        self.anchors.add(unit.anchor)
        self.units.append(unit)
        state.open = unit

    def node(self, anchor: str, kind: str, number: str, title: str, parent: str | None) -> None:
        if any(n.anchor == anchor for n in self.structure):
            raise RegulationFormatError(f"The heading {anchor} appears twice in the statement.")
        self.structure.append(StructureNode(anchor, kind, number, title, parent))

    def strip_markers(self, line: _Line) -> str:
        """Return a line's text without superscript markers, and record the markers."""
        kept: list[str] = []
        for text, height in line.words:
            if height < line.height * _MARK_RATIO:
                if not text.isdigit():
                    raise RegulationFormatError(
                        f"A small word {text!r} on page {line.page} is not a footnote number."
                    )
                self.markers.append(int(text))
            else:
                kept.append(text)
        return " ".join(kept)

    def run(self) -> None:
        heights = Counter(round(line.height, 1) for line in self.lines)
        body = heights.most_common(1)[0][0]
        state = _State()
        started = False
        pending: _Line | None = None
        for line in self.lines:
            text = line.text
            if _RUNNING_HEAD.search(text):
                self.claim(line, "running head", furniture=True)
                continue
            if _PAGE_NUMBER.match(text):
                self.claim(line, "page number", furniture=True)
                continue
            if not started:
                if line.height >= body * 1.8 and _CHAPTER.match(text):
                    started = True
                else:
                    self.claim(line, "cover page", furniture=True)
                    continue
            if line.height <= body * _NOTE_RATIO_LOW and text.isdigit() and line.x < 56:
                self.labels.append((int(text), line.page, line.y))
                self.claim(line, "footnote")
                continue
            if body * _NOTE_RATIO_LOW < line.height < body * _NOTE_RATIO_HIGH:
                self.note_lines.append(line)
                self.claim(line, "footnote")
                continue
            clean = self.strip_markers(line)
            if line.height >= body * _HEADING_RATIO:
                if (
                    pending is not None
                    and abs(pending.height - line.height) < 0.5
                    and not (
                        _CHAPTER.match(clean)
                        or _PRINCIPLE.match(clean)
                        or _SUB_PRINCIPLE.match(clean)
                    )
                ):
                    pending.words.append((clean, line.height))
                    self.claim(line, "heading")
                    continue
                if pending is not None:
                    self.heading(pending, state)
                pending = _Line(
                    line.index, line.page, line.x, line.y, line.height, [(clean, line.height)]
                )
                self.claim(line, "heading")
                continue
            if pending is not None:
                self.heading(pending, state)
                pending = None
            self.body_line(line, clean, state, body)
        if pending is not None:
            self.heading(pending, state)

    def heading(self, line: _Line, state: _State) -> None:
        text = line.text
        state.open = None
        if m := _CHAPTER.match(text):
            number = int(m.group(1))
            self.chapters.append(number)
            state.chapter, state.topic, state.topic_count = number, None, 0
            state.principle, state.sub = 0, None
            self.node(f"chapter:{number}", "chapter", str(number), m.group(2), None)
        elif m := _PRINCIPLE.match(text):
            number = int(m.group(1))
            if state.chapter == 3:
                self.overview.append(number)
                self.start(
                    state,
                    _Unit(
                        f"ovw:{number}",
                        "principle_overview",
                        f"Principle {number}, overview",
                        ("chapter:3",),
                        m.group(2),
                    ),
                )
            else:
                self.principles.append(number)
                state.principle, state.sub = number, None
                self.node(
                    f"principle:{number}",
                    "principle",
                    str(number),
                    m.group(2),
                    f"chapter:{state.chapter}",
                )
                self.start(
                    state,
                    _Unit(
                        f"prin:{number}",
                        "principle_statement",
                        f"Principle {number}",
                        (f"chapter:{state.chapter}",),
                        m.group(2),
                    ),
                )
        elif m := _SUB_PRINCIPLE.match(text):
            major, minor = int(m.group(1)), int(m.group(2))
            state.sub = (major, minor)
            self.subs.setdefault(major, []).append(minor)
            self.node(
                f"subprinciple:{major}.{minor}",
                "subprinciple",
                f"{major}.{minor}",
                m.group(3),
                f"principle:{major}",
            )
            self.start(
                state,
                _Unit(
                    f"prin:{major}.{minor}",
                    "principle_lead",
                    f"Principle {major}.{minor}",
                    self.chain(state),
                    m.group(3),
                ),
            )
        else:
            state.topic_count += 1
            state.topic = f"topic:{state.chapter}.{state.topic_count}"
            self.node(
                state.topic, "topic", str(state.topic_count), text, f"chapter:{state.chapter}"
            )

    def chain(self, state: _State) -> tuple[str, ...]:
        parts = [f"chapter:{state.chapter}"]
        if state.topic:
            parts.append(state.topic)
        if state.principle:
            parts.append(f"principle:{state.principle}")
        if state.sub:
            parts.append(f"subprinciple:{state.sub[0]}.{state.sub[1]}")
        return tuple(parts)

    def body_line(self, line: _Line, clean: str, state: _State, body: float) -> None:
        if state.chapter in (1, 2, 3) and line.x <= 49.6 + _MARGIN_TOLERANCE:
            m = _PARAGRAPH.match(clean)
            if m and int(m.group(1)) == state.chapter:
                number = int(m.group(2))
                self.paragraphs.setdefault(state.chapter, []).append(number)
                unit = _Unit(
                    f"para:{state.chapter}.{number}",
                    "paragraph",
                    f"Paragraph {state.chapter}.{number}",
                    self.chain(state),
                    "",
                )
                unit.lines.append(
                    _Line(
                        line.index,
                        line.page,
                        line.x,
                        line.y,
                        line.height,
                        [(m.group(3), line.height)],
                    )
                )
                self.start(state, unit)
                self.claim(line, unit.anchor)
                self.noted(unit, line)
                return
        if state.sub is not None and line.x > 49.6 + _POINT_INDENT:
            m = _POINT.match(clean)
            if m:
                major, minor = state.sub
                letter = m.group(1)
                self.points.setdefault(state.sub, []).append(f"({letter})")
                unit = _Unit(
                    f"prin:{major}.{minor}/{letter}",
                    "principle_point",
                    f"Principle {major}.{minor}({letter})",
                    self.chain(state),
                    "",
                )
                unit.lines.append(
                    _Line(
                        line.index,
                        line.page,
                        line.x,
                        line.y,
                        line.height,
                        [(m.group(2), line.height)],
                    )
                )
                self.start(state, unit)
                self.claim(line, unit.anchor)
                self.noted(unit, line)
                return
        if state.open is None:
            return  # stays unclaimed; the closure names it
        state.open.lines.append(
            _Line(line.index, line.page, line.x, line.y, line.height, [(clean, line.height)])
        )
        self.claim(line, state.open.anchor)
        self.noted(state.open, line)

    def noted(self, unit: _Unit, line: _Line) -> None:
        for text, height in line.words:
            if height < line.height * _MARK_RATIO and text.isdigit():
                unit.notes.append(int(text))

    def footnotes(self) -> list[RegUnit]:
        """Place each footnote line under the label that opens it, and make the notes' units."""
        if not self.labels and self.markers:
            raise RegulationFormatError(
                f"Footnote marker(s) {', '.join(map(str, sorted(set(self.markers))))} are in the "
                "text and the statement holds no footnote."
            )
        by_page: dict[int, list[tuple[int, float]]] = {}
        for number, page, y in self.labels:
            by_page.setdefault(page, []).append((number, y))
        texts: dict[int, list[str]] = {number: [] for number, _, _ in self.labels}
        for line in self.note_lines:
            owners = [(y, n) for n, y in by_page.get(line.page, []) if y <= line.y + 1.5]
            if not owners:
                raise RegulationFormatError(
                    f"A footnote line on page {line.page} has no footnote number: "
                    f"{line.text[:60]!r}."
                )
            texts[max(owners)[1]].append(line.text)
        numbers = [number for number, _, _ in self.labels]
        _check_numbers(numbers, "Footnote")
        absent = sorted(set(self.markers) - set(numbers))
        if absent:
            raise RegulationFormatError(
                f"Footnote marker(s) {', '.join(map(str, absent))} have no footnote in the "
                "statement."
            )
        unreferenced = sorted(set(numbers) - set(self.markers))
        if unreferenced:
            raise RegulationFormatError(
                f"Footnote(s) {', '.join(map(str, unreferenced))} are never marked in the text."
            )
        out: list[RegUnit] = []
        for number in numbers:
            text = _join(texts[number])
            if not text:
                raise RegulationFormatError(f"Footnote {number} has no text.")
            out.append(RegUnit(f"note:{number}", "footnote", f"Footnote {number}", text))
        return out

    def finish(self) -> list[RegUnit]:
        if not self.chapters:
            raise RegulationFormatError("The statement holds no numbered chapter.")
        _check_numbers(self.chapters, "Chapter")
        for chapter, numbers in self.paragraphs.items():
            _check_numbers(numbers, f"Paragraph {chapter}.", dotted=True)
        _check_numbers(self.overview, "Principle (overview) ")
        _check_numbers(self.principles, "Principle ")
        for major, minors in self.subs.items():
            _check_numbers(minors, f"Principle {major}.", dotted=True)
        items: list[RegUnit] = []
        for unit in self.units:
            text = _join([line.text for line in unit.lines])
            if not text:
                if unit.kind == "principle_lead":
                    continue  # a sub-principle with no lead sentence has no lead unit
                raise RegulationFormatError(f"The unit {unit.anchor} ({unit.label}) holds no text.")
            items.append(
                RegUnit(
                    unit.anchor,
                    unit.kind,
                    unit.label,
                    text,
                    parents=unit.parents,
                    heading=unit.heading,
                    note_numbers=tuple(unit.notes),
                )
            )
        for sub, labels in self.points.items():
            gap = sequence_gap(labels)
            if gap is not None:
                raise RegulationFormatError(
                    f"Point ({gap[0]}) of Principle {sub[0]}.{sub[1]} is missing: the points run "
                    f"{', '.join(labels)}."
                )
        items.extend(self.footnotes())
        unclaimed = [line for line in self.lines if line.index not in self.claims]
        if unclaimed:
            count = len(unclaimed)
            sample = "; ".join(repr(line.text[:50]) for line in unclaimed[:3])
            raise RegulationFormatError(
                f"{count} line{'s' if count != 1 else ''} {'are' if count != 1 else 'is'} not "
                f"claimed by any unit, heading or furniture class, for example {sample}."
            )
        return items


def _check_numbers(numbers: list[int], prefix: str, *, dotted: bool = False) -> None:
    expected = 1
    for number in numbers:
        if number == expected - 1 and numbers.count(number) > 1:
            raise RegulationFormatError(f"{prefix}{number} appears twice in the statement.")
        if number > expected:
            raise RegulationFormatError(
                f"{prefix}{expected} is missing: the numbering jumps from "
                f"{expected - 1} to {number}."
            )
        expected = number + 1


def read_supervisory_statement(
    pdf: bytes, *, key: str, title: str, locator: str, terms: str, layout: bytes | None = None
) -> RegulationRead:
    """Read a supervisory statement PDF into units.

    Args:
        pdf: The PDF's bytes as fetched; its digest is the source's digest.
        key: The statement's key in the build, for example ``SS1-23``.
        title: The statement's title.
        locator: The address the bytes were fetched from.
        terms: The terms on which the statement may be reused, as recorded.
        layout: The word positions of the PDF, when already made; otherwise ``pdftotext`` makes
            them.

    Returns:
        The statement read, with its headings, units and the closure of the reading.

    Raises:
        RegulationToolMissingError: If the layout is needed and ``pdftotext`` is not installed.
        RegulationFormatError: If the layout is not well-formed, the numbering has a gap or a
            repeat, a footnote marker has no note, or a line is claimed by nothing.
    """
    lines = _parse(layout if layout is not None else layout_from_pdf(pdf))
    reader = _Reader(lines)
    reader.run()
    items = reader.finish()
    source = Source.build(
        key=key,
        title=title,
        kind="supervisory_statement",
        digest=digest_bytes(pdf),
        locator=locator,
        terms=terms,
    )
    closure = Closure(
        elements_total=len(lines),
        elements_claimed=len(reader.claims),
        furniture=dict(reader.furniture),
        unit_total=len(items),
    )
    return assemble(source=source, structure=reader.structure, items=items, closure=closure)
