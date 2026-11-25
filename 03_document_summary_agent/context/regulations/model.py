"""The records a regulation is read into: structure, units and the closure of the reading."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from fsi_common.records import Source, SourceUnit


@dataclass(frozen=True)
class StructureNode:
    """One heading of a regulation: a title, chapter, section, article, annex or group.

    Attributes:
        anchor: The node's anchor, for example ``article:6`` or ``chapter:III``.
        kind: ``title``, ``chapter``, ``section``, ``article``, ``annex``, ``group`` or
            ``principle``.
        number: The number as the regulation writes it (``6``, ``III``).
        title: The heading's title, empty when the regulation gives none.
        parent: The anchor of the node it sits under, or None at the top.
    """

    anchor: str
    kind: str
    number: str
    title: str
    parent: str | None


@dataclass(frozen=True)
class RegUnit:
    """One citable unit of a regulation: a recital, a paragraph, a point, an annex item.

    Attributes:
        anchor: The unit's anchor, for example ``art:6/3``.
        kind: The unit's kind, for example ``recital`` or ``article_paragraph``.
        label: How a reader cites it, for example ``Article 6(3)``.
        text: The unit's text without its own number, points and sub-points inline.
        parents: Anchors of the structure it sits under, outermost first.
        heading: The title of the article or sub-principle it belongs to, or empty.
        points: Labels of the unit's top-level points, in order.
        note_numbers: Numbers of the footnote markers that stood in the text.
        paragraph_indexes: Positions, in document order, of the source paragraph elements the
            unit claims, so a check can rebuild the unit's text from the source.
    """

    anchor: str
    kind: str
    label: str
    text: str
    parents: tuple[str, ...] = ()
    heading: str = ""
    points: tuple[str, ...] = ()
    note_numbers: tuple[int, ...] = ()
    paragraph_indexes: tuple[int, ...] = ()


@dataclass(frozen=True)
class Closure:
    """What the reader claimed of the document, so that nothing is dropped unseen.

    Attributes:
        elements_total: The paragraph elements (or lines, for a PDF) the document holds.
        elements_claimed: Those the reader placed in a unit, a heading or a recorded furniture
            class.
        furniture: Count of each furniture class (running headers, signatures and the like).
        unit_total: The units read.
        irregular_lists: Anchors of units whose point labels do not run in a plain sequence; they
            are listed, not hidden.
    """

    elements_total: int
    elements_claimed: int
    furniture: dict[str, int]
    unit_total: int
    irregular_lists: tuple[str, ...] = ()

    @property
    def line(self) -> str:
        """The line that states the closure in words."""
        furniture = sum(self.furniture.values())
        return (
            f"{self.elements_claimed} of {self.elements_total} text elements accounted for "
            f"({furniture} furniture), {self.unit_total} units read"
        )


@dataclass(frozen=True)
class RegulationRead:
    """A regulation read whole: its source, its headings, its units and the closure.

    The ``units`` and ``unit_text`` match what the engine holds for a document, so the same
    accounting and fact records work on a regulation as on the starter's statement.
    """

    source: Source
    structure: tuple[StructureNode, ...]
    items: tuple[RegUnit, ...]
    units: tuple[SourceUnit, ...]
    unit_text: dict[str, str]
    closure: Closure
    _by_anchor: dict[str, RegUnit] = field(default_factory=dict, repr=False, compare=False)
    _nodes: dict[str, StructureNode] = field(default_factory=dict, repr=False, compare=False)

    def unit(self, anchor: str) -> RegUnit:
        """Return the unit an anchor names.

        Args:
            anchor: A unit anchor such as ``art:6/3``.

        Returns:
            The unit.

        Raises:
            KeyError: If the regulation has no such unit.
        """
        return self._by_anchor[anchor]

    def text(self, anchor: str) -> str:
        """Return the text of the unit an anchor names.

        Args:
            anchor: A unit anchor.

        Returns:
            The unit's text.
        """
        return self._by_anchor[anchor].text

    def node(self, anchor: str) -> StructureNode:
        """Return the heading an anchor names.

        Args:
            anchor: A structure anchor such as ``chapter:III``.

        Returns:
            The heading.

        Raises:
            KeyError: If the regulation has no such heading.
        """
        return self._nodes[anchor]

    def structure_counts(self) -> dict[str, int]:
        """Count the headings by kind.

        Returns:
            Each kind that occurs, with its count.
        """
        return dict(Counter(n.kind for n in self.structure))

    def unit_counts(self) -> dict[str, int]:
        """Count the units by kind.

        Returns:
            Each kind that occurs, with its count.
        """
        return dict(Counter(u.kind for u in self.items))


def assemble(
    *,
    source: Source,
    structure: list[StructureNode],
    items: list[RegUnit],
    closure: Closure,
) -> RegulationRead:
    """Build a regulation read from its parts, with the unit records and the lookups.

    Args:
        source: The source record.
        structure: The headings, in document order.
        items: The units, in document order.
        closure: The closure of the reading.

    Returns:
        The regulation read.
    """
    from fsi_common.ids import digest_text

    units = tuple(
        SourceUnit.build(source_id=source.id, anchor=i.anchor, text_digest=digest_text(i.text))
        for i in items
    )
    return RegulationRead(
        source=source,
        structure=tuple(structure),
        items=tuple(items),
        units=units,
        unit_text={u.id: i.text for u, i in zip(units, items, strict=True)},
        closure=closure,
        _by_anchor={i.anchor: i for i in items},
        _nodes={n.anchor: n for n in structure},
    )
