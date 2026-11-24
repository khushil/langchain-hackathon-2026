"""Read a document from the library into a source, its sections and one unit per paragraph."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from context.errors import DocumentFormatError, DocumentNotFoundError
from fsi_common.ids import digest_bytes, digest_text
from fsi_common.records import Source, SourceUnit
from tools.documents import get_document
from utils import PROJECT_ROOT, db
from utils.db import DATA_DIR
from utils.records import paragraph_anchor

SOURCE_TERMS = (
    "Fictional sample data from the FSI hackathon starter "
    "(github.com/langchain-samples/fsi-hackathon-london-2026), carried with credit"
)
"""The terms recorded for every source this topic reads: the starter's fictional data."""

_BLOCKS = re.compile(r"\n\s*\n")
_PARAGRAPH = re.compile(r"^(\d+)\.(\d+) (\S.*)$", re.DOTALL)


@dataclass(frozen=True)
class Paragraph:
    """One numbered paragraph, with its text as the document writes it after the number."""

    number: str
    section: str
    text: str

    @property
    def anchor(self) -> str:
        """The paragraph's anchor, for example ``para:7.1``."""
        return paragraph_anchor(self.number)


@dataclass(frozen=True)
class SectionRead:
    """One section as the starter splits it, with its paragraphs."""

    number: str
    title: str
    text: str
    paragraphs: tuple[Paragraph, ...]


@dataclass(frozen=True)
class DocumentRead:
    """A document read whole: its source, its sections, and a unit for each paragraph."""

    source: Source
    sections: tuple[SectionRead, ...]
    units: tuple[SourceUnit, ...]
    unit_text: dict[str, str] = field(default_factory=dict)

    def paragraph(self, anchor: str) -> Paragraph | None:
        """Return the paragraph an anchor names.

        Args:
            anchor: An anchor such as ``para:7.1``.

        Returns:
            The paragraph, or None when the document has none.
        """
        for section in self.sections:
            for paragraph in section.paragraphs:
                if paragraph.anchor == anchor:
                    return paragraph
        return None

    def section(self, number: str) -> SectionRead | None:
        """Return a section by its number.

        Args:
            number: The section number, for example ``7``.

        Returns:
            The section, or None when the document has none.
        """
        return next((s for s in self.sections if s.number == number), None)


def paragraph_unit(source: Source, paragraph: Paragraph) -> SourceUnit:
    """Return the unit a paragraph is read as.

    Args:
        source: The document the paragraph is from.
        paragraph: The paragraph.

    Returns:
        The unit, whose digest is that of the paragraph's text without its number.
    """
    return SourceUnit.build(
        source_id=source.id, anchor=paragraph.anchor, text_digest=digest_text(paragraph.text)
    )


def parse_paragraphs(section: str, text: str) -> tuple[Paragraph, ...]:
    """Split a section's text into its numbered paragraphs.

    Args:
        section: The section number the paragraphs must be numbered for.
        text: The section's text without its heading; paragraphs are separated by a blank line.

    Returns:
        The paragraphs in order, each without its number.

    Raises:
        DocumentFormatError: If a block is not a numbered paragraph of this section, a number
            appears twice, or the section holds no paragraph. Nothing is skipped.
    """
    paragraphs: list[Paragraph] = []
    for block in (b.strip() for b in _BLOCKS.split(text)):
        if not block:
            continue
        match = _PARAGRAPH.match(block)
        if match is None:
            raise DocumentFormatError(
                f"In section {section} the block '{block[:60]}' is not a numbered paragraph."
            )
        number = f"{match.group(1)}.{match.group(2)}"
        if match.group(1) != section:
            raise DocumentFormatError(
                f"Paragraph {number} is in the text of section {section}, so it is numbered for "
                "another section."
            )
        if any(p.number == number for p in paragraphs):
            raise DocumentFormatError(f"Paragraph {number} appears twice in section {section}.")
        paragraphs.append(Paragraph(number=number, section=section, text=match.group(3)))
    if not paragraphs:
        raise DocumentFormatError(f"Section {section} holds no paragraph.")
    return tuple(paragraphs)


def relative_locator(path_in_data: str) -> str:
    """Return a data file's path relative to the repository root.

    Args:
        path_in_data: The path inside the topic's ``data`` folder.

    Returns:
        The path from the repository root, for example
        ``03_document_summary_agent/data/firms.jsonl``.
    """
    return (DATA_DIR / path_in_data).relative_to(PROJECT_ROOT.parent).as_posix()


def read_document(document_id: str) -> DocumentRead:
    """Read a library document into a source, sections and paragraph units.

    The sections are the starter's own split; the source's digest is of the file's bytes, and each
    unit's digest is of its paragraph's text without the number. Two reads give identical records.

    Args:
        document_id: The document's id in the library, for example ``PS26-4``.

    Returns:
        The document read.

    Raises:
        DocumentNotFoundError: If the library has no such document.
        DocumentFormatError: If a section is not made of numbered paragraphs.
    """
    row = db.get("documents", document_id=document_id)
    if row is None:
        raise DocumentNotFoundError(f"There is no document {document_id} in the library.")
    path = DATA_DIR / "documents" / row["document_file"]
    document = get_document(document_id)
    source = Source.build(
        key=document_id,
        title=document["title"],
        kind="document",
        digest=digest_bytes(path.read_bytes()),
        locator=relative_locator(f"documents/{row['document_file']}"),
        terms=SOURCE_TERMS,
    )
    sections = tuple(
        SectionRead(
            number=s["number"],
            title=s["title"],
            text=s["text"],
            paragraphs=parse_paragraphs(s["number"], s["text"]),
        )
        for s in document["sections"]
    )
    units: list[SourceUnit] = []
    unit_text: dict[str, str] = {}
    for section in sections:
        for paragraph in section.paragraphs:
            unit = paragraph_unit(source, paragraph)
            units.append(unit)
            unit_text[unit.id] = paragraph.text
    return DocumentRead(source=source, sections=sections, units=tuple(units), unit_text=unit_text)
