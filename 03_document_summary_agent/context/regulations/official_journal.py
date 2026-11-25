"""Read an act of the Official Journal, as the Publications Office serves it, into units.

The markup is the Publications Office's XHTML: subdivisions with ids (recitals ``rct_N``,
articles ``art_N``, chapters ``cpt_X``), articles whose numbered paragraphs are divs, points set as
tables, annexes as containers, footnotes as ``oj-note`` paragraphs. Every paragraph element of the
document is placed in a unit, a heading or a named furniture class, or the read is refused, so a
dropped article, paragraph or point cannot pass unseen.
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace

from context.regulations.errors import RegulationFormatError
from context.regulations.lists import is_regular, sequence_gap
from context.regulations.model import Closure, RegulationRead, RegUnit, StructureNode, assemble
from fsi_common.ids import digest_bytes
from fsi_common.records import Source

NS = "{http://www.w3.org/1999/xhtml}"
_PARAGRAPH_ID = re.compile(r"^(\d{3})\.(\d{3})$")
_ARTICLE_ID = re.compile(r"^art_(\d+)$")
_CHAPTER_ID = re.compile(r"^cpt_([IVXLC]+)$")
_SECTION_ID = re.compile(r"^cpt_[IVXLC]+\.sct_\w+$")
_ANNEX_ID = re.compile(r"^anx_([IVXLC]+)$")
_RECITAL_ID = re.compile(r"^rct_(\d+)$")
_CITATION_ID = re.compile(r"^cit_(\d+)$")
_NUMERIC_LABEL = re.compile(r"^(?:\((\d+)\)|(\d+)\.)$")
_LEADING_NUMBER = re.compile(r"^(\d+)\.\s+")
_NOTE = re.compile(r"^\((\d+)\)\s*(.*)$", re.DOTALL)
_BLOCK_TAGS = {"p", "td", "tr", "table", "div", "tbody", "li", "br"}


def _tag(element: ET.Element) -> str:
    return element.tag.removeprefix(NS)


def _classes(element: ET.Element) -> set[str]:
    return set((element.get("class") or "").split())


def flatten(element: ET.Element, *, notes: list[int] | None = None) -> str:
    """Return an element's text in one line, without footnote markers.

    Args:
        element: The element.
        notes: When given, the numbers of the footnote markers found are appended to it.

    Returns:
        The text with white space collapsed, in NFC.
    """
    parts: list[str] = []

    def is_reference(node: ET.Element) -> bool:
        return _tag(node) == "a" and any("oj-note-tag" in _classes(e) for e in node.iter())

    def walk(node: ET.Element) -> None:
        parts.append(node.text or "")
        for child in node:
            if is_reference(child):
                if notes is not None:
                    tag = next(e for e in child.iter() if "oj-note-tag" in _classes(e))
                    label = "".join(tag.itertext()).strip()
                    if label.isdigit():  # a starred note belongs to quoted text of another act
                        notes.append(int(label))
                tail = child.tail or ""
                if tail[:1] in {",", ".", ";", ":", ")"}:
                    parts[-1:] = [parts[-1].rstrip()] if parts else []
                parts.append(tail)
                continue
            walk(child)
            if _tag(child) in _BLOCK_TAGS:
                parts.append(" ")
            parts.append(child.tail or "")

    walk(element)
    return unicodedata.normalize("NFC", " ".join("".join(parts).split()))


def _paragraphs(element: ET.Element) -> list[ET.Element]:
    return [e for e in element.iter() if _tag(e) == "p"]


@dataclass
class _Reader:
    key: str
    root: ET.Element
    items: list[RegUnit] = field(default_factory=list)
    structure: list[StructureNode] = field(default_factory=list)
    claims: dict[int, str] = field(default_factory=dict)
    furniture: dict[str, int] = field(default_factory=dict)
    irregular: list[str] = field(default_factory=list)
    markers: list[int] = field(default_factory=list)
    articles: list[int] = field(default_factory=list)
    recitals: list[int] = field(default_factory=list)
    citations: list[int] = field(default_factory=list)
    notes: list[int] = field(default_factory=list)
    anchors: set[str] = field(default_factory=set)
    roots: list[ET.Element] = field(default_factory=list)
    position: dict[int, int] = field(default_factory=dict)

    def claim(self, element: ET.Element, what: str, *, furniture: bool = False) -> None:
        self.roots.append(element)
        for p in _paragraphs(element) if _tag(element) != "p" else [element]:
            if id(p) in self.claims:
                raise RegulationFormatError(
                    f"A paragraph element is placed twice, as {self.claims[id(p)]} and as {what}."
                )
            self.claims[id(p)] = what
            if furniture:
                self.furniture[what] = self.furniture.get(what, 0) + 1

    def add_unit(self, unit: RegUnit, elements: list[ET.Element]) -> None:
        if unit.anchor in self.anchors:
            raise RegulationFormatError(
                f"The unit {unit.anchor} ({unit.label}) appears twice in the document."
            )
        self.anchors.add(unit.anchor)
        self.markers.extend(unit.note_numbers)
        indexes: list[int] = []
        for element in elements:
            self.claim(element, unit.anchor)
            indexes.extend(self.position[id(p)] for p in _paragraphs(element))
        unit = replace(unit, paragraph_indexes=tuple(sorted(set(indexes))))
        self.items.append(unit)
        labels = list(unit.points)
        if is_regular(labels):
            gap = sequence_gap(labels)
            if gap is not None:
                raise RegulationFormatError(
                    f"Point ({gap[0]}) of {unit.label} is missing: the points run "
                    f"{', '.join(labels)} and a point after ({gap[1]}) is not there."
                )
        elif len(labels) >= 2:
            self.irregular.append(unit.anchor)

    def add_node(self, node: StructureNode) -> None:
        if any(n.anchor == node.anchor for n in self.structure):
            raise RegulationFormatError(f"The heading {node.anchor} appears twice.")
        self.structure.append(node)


def _first_cell_label(table: ET.Element) -> str:
    cell = next((e for e in table.iter() if _tag(e) == "td"), None)
    return flatten(cell) if cell is not None else ""


def _content_cell(table: ET.Element) -> ET.Element | None:
    cells = [e for e in table.iter() if _tag(e) == "td"]
    return cells[1] if len(cells) > 1 else None


def _own_points(blocks: list[ET.Element]) -> tuple[str, ...]:
    labels: list[str] = []
    for block in blocks:
        if _tag(block) == "table":
            label = _first_cell_label(block)
            if label:
                labels.append(label)
        elif _tag(block) == "div":
            labels.extend(_own_points(list(block)))
    return tuple(labels)


def _numeric_item(block: ET.Element) -> int | None:
    """Return the number a block opens as a numbered item, or None when it does not."""
    if _tag(block) == "table":
        match = _NUMERIC_LABEL.match(_first_cell_label(block))
        if match:
            return int(match.group(1) or match.group(2))
    elif _tag(block) == "div" and "oj-enumeration-spacing" in _classes(block):
        match = _LEADING_NUMBER.match(flatten(block))
        if match:
            return int(match.group(1))
    return None


def _split_items(
    blocks: list[ET.Element],
) -> tuple[list[ET.Element], list[tuple[int, list[ET.Element]]]]:
    """Split a body into the blocks before the first numbered item and each numbered item."""
    lead: list[ET.Element] = []
    items: list[tuple[int, list[ET.Element]]] = []
    for block in blocks:
        number = _numeric_item(block)
        if number is not None:
            items.append((number, [block]))
        elif items:
            items[-1][1].append(block)
        else:
            lead.append(block)
    return lead, items


def _item_text(blocks: list[ET.Element], notes: list[int]) -> str:
    first, rest = blocks[0], blocks[1:]
    if _tag(first) == "table":
        cell = _content_cell(first)
        head = flatten(cell, notes=notes) if cell is not None else ""
    else:
        head = _LEADING_NUMBER.sub("", flatten(first, notes=notes), count=1)
    return " ".join([head, *(flatten(b, notes=notes) for b in rest)]).strip()


def _check_run(numbers: list[int], label_of, *, start: int = 1) -> None:
    expected = start
    for number in numbers:
        if number > expected:
            where = (
                f"jumps from {expected - 1} to {number}"
                if expected > start
                else f"starts at {number}"
            )
            raise RegulationFormatError(f"{label_of(expected)} is missing: the numbering {where}.")
        expected = number + 1


def _text_of(blocks: list[ET.Element], notes: list[int]) -> str:
    return " ".join(flatten(b, notes=notes) for b in blocks).strip()


def _group_label(heading: str) -> str:
    """Return the short name of an annex's group heading, for citing a unit inside it."""
    named = re.match(r"(?i)(section\s+\w+)", heading)
    if named:
        return named.group(1)
    return re.split(r"\s+[—–]\s+", heading, maxsplit=1)[0].strip()


class OjReader(_Reader):
    """Walks the document once and fills the units, headings and claims."""

    def run(self) -> None:
        body = next((e for e in self.root.iter() if _tag(e) == "body"), None)
        if body is None:
            raise RegulationFormatError("The document has no body.")
        for child in body:
            if _tag(child) == "table":
                self.claim(child, "running header", furniture=True)
            else:
                self.walk(child, ())
        self.finish()

    def walk(self, element: ET.Element, parents: tuple[str, ...]) -> None:
        tag, ident = _tag(element), element.get("id") or ""
        if tag == "p":
            self.loose_paragraph(element)
            return
        if tag != "div":
            if tag not in {"hr", "table"}:
                for child in element:
                    self.walk(child, parents)
            return
        if "eli-main-title" in _classes(element):
            self.title(element)
        elif ident.startswith("pbl_"):
            self.preamble(element)
        elif _CITATION_ID.match(ident) or _RECITAL_ID.match(ident):
            self.preamble_unit(element)
        elif _CHAPTER_ID.match(ident):
            self.chapter(element, parents)
        elif _SECTION_ID.match(ident):
            self.section(element, parents)
        elif _ARTICLE_ID.match(ident):
            self.article(element, parents)
        elif _ANNEX_ID.match(ident):
            self.annex(element)
        elif ident.startswith("fnp_"):
            self.final(element)
        else:
            for child in element:
                self.walk(child, parents)

    def loose_paragraph(self, element: ET.Element) -> None:
        text = flatten(element)
        classes = _classes(element)
        if "oj-note" in classes and _NOTE.match(text):
            match = _NOTE.match(text)
            assert match is not None  # noqa: S101 - the same pattern matched on the line above
            number = int(match.group(1))
            self.notes.append(number)
            self.add_unit(
                RegUnit(
                    anchor=f"note:{number}",
                    kind="footnote",
                    label=f"Footnote {number}",
                    text=match.group(2).strip(),
                ),
                [element],
            )
        elif text.upper().startswith("HAVE ADOPTED"):
            self.claim(element, "preamble formula", furniture=True)
        elif text.startswith(("ELI:", "ISSN ")):
            self.claim(element, "document footer", furniture=True)
        # Any other loose paragraph stays unclaimed and fails the closure, by name.

    def title(self, element: ET.Element) -> None:
        text = " ".join(flatten(p) for p in _paragraphs(element))
        self.add_node(StructureNode("title:1", "title", "1", text, None))
        self.claim(element, "title")

    def preamble(self, element: ET.Element) -> None:
        for child in element:
            if _tag(child) == "p":
                self.claim(child, "preamble formula", furniture=True)
            else:
                self.walk(child, ())

    def preamble_unit(self, element: ET.Element) -> None:
        ident = element.get("id") or ""
        notes: list[int] = []
        if (m := _RECITAL_ID.match(ident)) is not None:
            number = int(m.group(1))
            self.recitals.append(number)
            cells = [e for e in element.iter() if _tag(e) == "td"]
            if len(cells) < 2 or flatten(cells[0]) != f"({number})":
                raise RegulationFormatError(f"Recital {number} does not open with its number.")
            text = flatten(cells[1], notes=notes)
            unit = RegUnit(
                f"rct:{number}", "recital", f"Recital {number}", text, note_numbers=tuple(notes)
            )
        else:
            m = _CITATION_ID.match(ident)
            assert m is not None  # noqa: S101 - the caller matched one of the two patterns
            number = int(m.group(1))
            self.citations.append(number)
            unit = RegUnit(
                f"cit:{number}",
                "citation",
                f"Citation {number}",
                flatten(element, notes=notes),
                note_numbers=tuple(notes),
            )
        self.add_unit(unit, [element])

    def heading_number(self, element: ET.Element, pattern: str) -> str:
        head = next((p for p in element if _tag(p) == "p"), None)
        match = re.search(pattern, flatten(head) if head is not None else "", re.IGNORECASE)
        if match is None:
            raise RegulationFormatError(f"A heading of {element.get('id')} has no number.")
        return match.group(1).upper() if match.group(1).isalpha() else match.group(1)

    def heading_title(self, element: ET.Element) -> str:
        title = next((c for c in element if "eli-title" in _classes(c)), None)
        return flatten(title) if title is not None else ""

    def claim_headings(self, element: ET.Element, what: str) -> None:
        for child in element:
            if _tag(child) == "p" or "eli-title" in _classes(child):
                self.claim(child, what)

    def chapter(self, element: ET.Element, parents: tuple[str, ...]) -> None:
        number = self.heading_number(element, r"chapter\s+([IVXLC]+)")
        anchor = f"chapter:{number}"
        self.add_node(StructureNode(anchor, "chapter", number, self.heading_title(element), None))
        self.claim_headings(element, anchor)
        for child in element:
            if _tag(child) == "div" and "eli-title" not in _classes(child):
                self.walk(child, (anchor,))

    def section(self, element: ET.Element, parents: tuple[str, ...]) -> None:
        number = self.heading_number(element, r"section\s+(\w+)")
        chapter = parents[0].split(":")[1] if parents else "?"
        anchor = f"section:{chapter}.{number}"
        self.add_node(
            StructureNode(
                anchor,
                "section",
                number,
                self.heading_title(element),
                parents[-1] if parents else None,
            )
        )
        self.claim_headings(element, anchor)
        for child in element:
            if _tag(child) == "div" and "eli-title" not in _classes(child):
                self.walk(child, (*parents, anchor))

    def article(self, element: ET.Element, parents: tuple[str, ...]) -> None:
        ident = element.get("id") or ""
        match = _ARTICLE_ID.match(ident)
        if match is None:
            raise RegulationFormatError(f"The subdivision {ident} is not an article.")
        number = int(match.group(1))
        head = next((c for c in element if _tag(c) == "p" and "oj-ti-art" in _classes(c)), None)
        if head is None or flatten(head) != f"Article {number}":
            raise RegulationFormatError(f"{ident} does not open with the heading Article {number}.")
        self.articles.append(number)
        title_div = next((c for c in element if "eli-title" in _classes(c)), None)
        title = flatten(title_div) if title_div is not None else ""
        anchor = f"article:{number}"
        self.add_node(
            StructureNode(anchor, "article", str(number), title, parents[-1] if parents else None)
        )
        self.claim(head, anchor)
        if title_div is not None:
            self.claim(title_div, anchor)
        chain = (*parents, anchor)
        body = [c for c in element if c is not head and c is not title_div]
        numbered = [c for c in body if _PARAGRAPH_ID.match(c.get("id") or "") and _tag(c) == "div"]
        if numbered:
            others = [c for c in body if c not in numbered and flatten(c)]
            if others:
                raise RegulationFormatError(
                    f"Article {number} mixes numbered paragraphs with loose text: "
                    f"{flatten(others[0])[:60]!r}."
                )
            self.numbered_paragraphs(number, title, numbered, chain)
        else:
            self.loose_article(number, title, body, chain)

    def numbered_paragraphs(
        self, number: int, title: str, divs: list[ET.Element], chain: tuple[str, ...]
    ) -> None:
        seen: list[int] = []
        for div in divs:
            match = _PARAGRAPH_ID.match(div.get("id") or "")
            assert match is not None  # noqa: S101 - the caller filtered on this pattern
            paragraph = int(match.group(2))
            if seen and paragraph == seen[-1]:
                raise RegulationFormatError(
                    f"The unit art:{number}/{paragraph} appears twice in Article {number}."
                )
            if paragraph != (seen[-1] + 1 if seen else 1):
                missing = seen[-1] + 1 if seen else 1
                raise RegulationFormatError(
                    f"Paragraph {missing} of Article {number} is missing: the numbering goes "
                    f"{'from ' + str(seen[-1]) + ' ' if seen else ''}to {paragraph}."
                )
            seen.append(paragraph)
            notes: list[int] = []
            text = flatten(div, notes=notes)
            lead = _LEADING_NUMBER.match(text)
            if lead and int(lead.group(1)) != paragraph:
                raise RegulationFormatError(
                    f"Paragraph {paragraph} of Article {number} opens with the number "
                    f"{lead.group(1)}."
                )
            text = _LEADING_NUMBER.sub("", text, count=1)
            self.add_unit(
                RegUnit(
                    f"art:{number}/{paragraph}",
                    "article_paragraph",
                    f"Article {number}({paragraph})",
                    text,
                    parents=chain,
                    heading=title,
                    points=_own_points(list(div)),
                    note_numbers=tuple(notes),
                ),
                [div],
            )

    def loose_article(
        self, number: int, title: str, body: list[ET.Element], chain: tuple[str, ...]
    ) -> None:
        blocks = [b for b in body if flatten(b) or _tag(b) == "table"]
        lead, items = _split_items(blocks)
        label = f"Article {number}"
        if not items:
            notes: list[int] = []
            self.add_unit(
                RegUnit(
                    f"art:{number}",
                    "article_body",
                    label,
                    _text_of(blocks, notes),
                    parents=chain,
                    heading=title,
                    points=_own_points(blocks),
                    note_numbers=tuple(notes),
                ),
                blocks,
            )
            return
        _check_run([n for n, _ in items], lambda k: f"Point ({k}) of {label}")
        if lead:
            notes = []
            self.add_unit(
                RegUnit(
                    f"art:{number}/lead",
                    "article_lead",
                    label,
                    _text_of(lead, notes),
                    parents=chain,
                    heading=title,
                    points=_own_points(lead),
                    note_numbers=tuple(notes),
                ),
                lead,
            )
        for item_number, item_blocks in items:
            notes = []
            text = _item_text(item_blocks, notes)
            cell = _content_cell(item_blocks[0]) if _tag(item_blocks[0]) == "table" else None
            points = _own_points(list(cell)) if cell is not None else ()
            self.add_unit(
                RegUnit(
                    f"art:{number}/pt{item_number}",
                    "article_point",
                    f"{label}, point ({item_number})",
                    text,
                    parents=chain,
                    heading=title,
                    points=points,
                    note_numbers=tuple(notes),
                ),
                item_blocks,
            )

    def annex(self, element: ET.Element) -> None:
        children = list(element)
        titles = [c for c in children if _tag(c) == "p" and "oj-doc-ti" in _classes(c)]
        if not titles:
            raise RegulationFormatError(f"{element.get('id')} has no heading.")
        match = re.match(r"ANNEX\s+([IVXLC]+)", flatten(titles[0]))
        if match is None:
            raise RegulationFormatError(
                f"{element.get('id')} does not open with ANNEX and a number."
            )
        number = match.group(1)
        anchor = f"annex:{number}"
        title = " ".join(flatten(t) for t in titles[1:])
        self.add_node(StructureNode(anchor, "annex", number, title, None))
        for t in titles:
            self.claim(t, anchor)
        label = f"Annex {number}"
        groups: list[tuple[str | None, list[ET.Element]]] = [(None, [])]
        for child in children:
            if child in titles:
                continue
            if _tag(child) == "p" and any(c.startswith("oj-ti-grseq") for c in _classes(child)):
                text = flatten(child)
                if groups[-1][0] is not None and not groups[-1][1]:
                    groups[-1] = (f"{groups[-1][0]} {text}", [])
                else:
                    groups.append((text, []))
                self.claim(child, anchor)
            else:
                groups[-1][1].append(child)
        index = 0
        for heading, blocks in groups:
            blocks = [b for b in blocks if flatten(b) or _tag(b) == "table"]
            if heading is not None:
                index += 1
                prefix = f"anx:{number}/s{index}"
                short = _group_label(heading)
                group_label = f"{label}, {short}"
                self.add_node(
                    StructureNode(f"group:{number}/s{index}", "group", short, heading, anchor)
                )
                parents = (anchor, f"group:{number}/s{index}")
            else:
                prefix, group_label, parents = f"anx:{number}", label, (anchor,)
            if not blocks:
                continue
            lead, items = _split_items(blocks)
            if not items:
                notes: list[int] = []
                self.add_unit(
                    RegUnit(
                        prefix,
                        "annex_body",
                        group_label,
                        _text_of(blocks, notes),
                        parents=parents,
                        heading=title,
                        points=_own_points(blocks),
                        note_numbers=tuple(notes),
                    ),
                    blocks,
                )
                continue
            _check_run([n for n, _ in items], lambda k, g=group_label: f"Point {k} of {g}")
            if lead:
                notes = []
                self.add_unit(
                    RegUnit(
                        f"{prefix}/lead",
                        "annex_lead",
                        group_label,
                        _text_of(lead, notes),
                        parents=parents,
                        heading=title,
                        points=_own_points(lead),
                        note_numbers=tuple(notes),
                    ),
                    lead,
                )
            for item_number, item_blocks in items:
                notes = []
                cell = _content_cell(item_blocks[0]) if _tag(item_blocks[0]) == "table" else None
                self.add_unit(
                    RegUnit(
                        f"{prefix}/{item_number}",
                        "annex_point",
                        f"{group_label}, point {item_number}",
                        _item_text(item_blocks, notes),
                        parents=parents,
                        heading=title,
                        points=_own_points(list(cell)) if cell is not None else (),
                        note_numbers=tuple(notes),
                    ),
                    item_blocks,
                )

    def final(self, element: ET.Element) -> None:
        signed: dict[int, ET.Element] = {}
        for e in element.iter():
            if "oj-signatory" in _classes(e):
                for p in [e] if _tag(e) == "p" else _paragraphs(e):
                    signed.setdefault(id(p), p)
        for p in signed.values():
            self.claim(p, "signature", furniture=True)
        formula = [p for p in _paragraphs(element) if id(p) not in self.claims]
        text = " ".join(flatten(p) for p in formula)
        self.add_unit(RegUnit("fin:1", "final_formula", "Final provisions", text), formula)

    def finish(self) -> None:
        if not self.articles:
            raise RegulationFormatError("The document holds no article, so it is not an act.")
        _check_run(self.articles, lambda k: f"Article {k}")
        _check_run(self.recitals, lambda k: f"Recital {k}")
        _check_run(self.citations, lambda k: f"Citation {k}")
        _check_run(self.notes, lambda k: f"Footnote {k}")
        absent = sorted(set(self.markers) - set(self.notes))
        if absent:
            raise RegulationFormatError(
                f"Footnote marker(s) {', '.join(map(str, absent))} have no footnote in the "
                "document."
            )
        unmarked = sorted(set(self.notes) - set(self.markers))
        if unmarked:
            raise RegulationFormatError(
                f"Footnote {unmarked[0]} is never marked in the text"
                + (f" (nor are {', '.join(map(str, unmarked[1:]))})" if len(unmarked) > 1 else "")
                + "."
            )
        every = _paragraphs(self.root)
        unclaimed = [p for p in every if id(p) not in self.claims]
        if unclaimed:
            sample = "; ".join(repr(flatten(p)[:50]) for p in unclaimed[:3])
            count = len(unclaimed)
            raise RegulationFormatError(
                f"{count} paragraph element{'s' if count != 1 else ''} "
                f"{'are' if count != 1 else 'is'} not claimed by any unit, heading or furniture "
                f"class, for example {sample}."
            )
        covered = {id(e) for root in self.roots for e in root.iter()}
        stray: list[str] = []
        for element in self.root.iter():
            if _tag(element) in {"title", "script", "style"}:
                continue
            if element.text and element.text.strip() and id(element) not in covered:
                stray.append(element.text.strip())
            for child in element:
                if child.tail and child.tail.strip() and id(element) not in covered:
                    stray.append(child.tail.strip())
        if stray:
            raise RegulationFormatError(
                f"{len(stray)} piece(s) of text outside any claimed paragraph or unit, for example "
                f"{stray[0][:60]!r}."
            )


def read_official_journal(
    data: bytes, *, key: str, title: str, locator: str, terms: str
) -> RegulationRead:
    """Read an Official Journal act, as the Publications Office serves it, into units.

    Args:
        data: The XHTML bytes as fetched.
        key: The regulation's key in the build, for example ``DORA``.
        title: The act's title.
        locator: The address the bytes were fetched from.
        terms: The terms on which the act may be reused, as recorded.

    Returns:
        The regulation read, with its headings, units and the closure of the reading.

    Raises:
        RegulationFormatError: If the document is not well-formed, holds no article, has a gap or
            repeat in its numbering, or has a paragraph element that no unit claims.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise RegulationFormatError(f"The document is not well-formed XHTML: {exc}.") from exc
    reader = OjReader(key=key, root=root)
    reader.position = {id(p): i for i, p in enumerate(_paragraphs(root))}
    reader.run()
    source = Source.build(
        key=key,
        title=title,
        kind="regulation",
        digest=digest_bytes(data),
        locator=locator,
        terms=terms,
    )
    closure = Closure(
        elements_total=len(_paragraphs(root)),
        elements_claimed=len(reader.claims),
        furniture=dict(reader.furniture),
        unit_total=len(reader.items),
        irregular_lists=tuple(reader.irregular),
    )
    return assemble(source=source, structure=reader.structure, items=reader.items, closure=closure)
