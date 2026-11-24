"""The picture of the document: its paragraphs in order, each marked by what was found in it.

It is drawn from the state of the run: the units the document was read into, the unit accounting,
the facts and their checks, and the open questions. Every paragraph read is in it once, and
the count beside it says how many of the paragraphs read are accounted for.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from fsi_common.records import Fact
from review_app.source_view import kind_label
from utils.records import FACT_CONTEXT

FAILED = "failed"
QUESTION = "question"
OBLIGATION = "obligation"
OTHER = "other"
NOTHING = "nothing"
PARAGRAPH_SCHEME = "para:"


@dataclass(frozen=True)
class Finding:
    """What was found in one paragraph: a word, a kind for the style and the detail for a hover."""

    kind: str
    word: str
    detail: str


@dataclass(frozen=True)
class MapCell:
    """One paragraph of the picture."""

    number: str
    anchor: str
    finding: Finding
    fact_id: str | None
    href: str
    current: bool


@dataclass(frozen=True)
class MapSection:
    """One section of the document with its paragraphs."""

    number: str
    title: str
    cells: tuple[MapCell, ...]


@dataclass(frozen=True)
class DocumentMap:
    """The sections read, and the count that closes."""

    sections: tuple[MapSection, ...]
    accounted: int
    total: int
    scope: str

    @property
    def count(self) -> str:
        """Say how many paragraphs read are accounted for."""
        return f"{self.accounted} of {self.total} paragraphs of {self.scope} accounted for"


def _natural(anchor: str) -> tuple[int, ...]:
    return tuple(
        int(p) if p.isdigit() else 0 for p in anchor.removeprefix(PARAGRAPH_SCHEME).split(".")
    )


def _scope(sections: Sequence[str] | None) -> str:
    if not sections:
        return "the document"
    if len(sections) == 1:
        return f"section {sections[0]}"
    return f"sections {', '.join(sections[:-1])} and {sections[-1]}"


def _finding(facts: Sequence[Fact], questions: Sequence[Mapping], reason: str | None) -> Finding:
    if not facts:
        return Finding(NOTHING, "No fact", reason or "No fact was read from this paragraph.")
    found = []
    failed = [f for f in facts if not f.passed_checks]
    obligations = [f for f in facts if f.kind == "obligation"]
    if failed:
        found.append(("Failed check", FAILED))
    if questions:
        found.append(("Open question", QUESTION))
    if obligations:
        deadline = any(f.attributes.get("deadline") for f in obligations)
        found.append(("Obligation, deadline" if deadline else "Obligation", OBLIGATION))
    kinds = dict.fromkeys(kind_label(f.kind) for f in facts if f.kind != "obligation")
    found += [(k, OTHER) for k in kinds]
    word, kind = found[0]
    return Finding(kind, word, "; ".join(w for w, _ in found))


def build_map(
    state: Mapping,
    *,
    sections: Sequence[str] | None,
    titles: Mapping[str, str],
    href_for: Callable[[str, Sequence[str]], str],
    current: str | None = None,
) -> DocumentMap | None:
    """Draw the document's paragraphs from a run's state.

    Args:
        state: The run's state: sources, facts, open questions and the unit accounting.
        sections: The sections the run was asked to read, or None for every section.
        titles: Each section's title by number.
        href_for: Gives the address that opens a paragraph, from its anchor and the ids of the
            facts read from it.
        current: The anchor of the paragraph open now, if any.

    Returns:
        The picture, or None when the state holds no accounting of a document.
    """
    sources = state.get("sources", {}) or {}
    accounting = next(
        (
            a
            for sid, a in (state.get("accounting", {}) or {}).items()
            if sources.get(sid, {}).get("kind") == "document"
        ),
        None,
    )
    if accounting is None:
        return None
    without = {u["anchor"]: u["reason"] for u in accounting["without_facts"]}
    anchors = sorted([*accounting["with_facts"], *without], key=_natural)
    by_anchor: dict[str, list[Fact]] = {}
    for contents in (state.get("facts", {}) or {}).values():
        for content in contents:
            fact = Fact.model_validate(content, context=FACT_CONTEXT)
            if fact.subject.source_id == accounting["source_id"]:
                by_anchor.setdefault(fact.subject.anchor, []).append(fact)
    questions = list((state.get("open_questions", {}) or {}).values())
    grouped: dict[str, list[MapCell]] = {}
    for anchor in anchors:
        held = by_anchor.get(anchor, [])
        ids = {f.id for f in held}
        asked = [
            q for q in questions if q["about"]["anchor"] == anchor or ids & set(q.get("cites", []))
        ]
        finding = _finding(held, asked, without.get(anchor))
        number = anchor.removeprefix(PARAGRAPH_SCHEME)
        fact_id = held[0].id if held else None
        cell = MapCell(
            number=number,
            anchor=anchor,
            finding=finding,
            fact_id=fact_id,
            href=href_for(anchor, [f.id for f in held]),
            current=anchor == current,
        )
        grouped.setdefault(number.split(".")[0], []).append(cell)
    return DocumentMap(
        sections=tuple(
            MapSection(number, titles.get(number, ""), tuple(found))
            for number, found in grouped.items()
        ),
        accounted=len(accounting["with_facts"]) + len(without),
        total=accounting["units_in"],
        scope=_scope(sections),
    )


@dataclass(frozen=True)
class ParagraphPanel:
    """A paragraph read, opened from the picture, with what became of it."""

    place: str
    source_title: str
    digest: str
    unit_text: str
    reason: str
    row: None = None
    segments: None = None
    quote_found: bool = True
    decision: None = None


def paragraph_panel(state: Mapping, number: str | None) -> ParagraphPanel | None:
    """Build the panel of a paragraph that gave no fact, from the state of the run.

    Args:
        state: The run's state.
        number: The paragraph's number, such as ``6.1``.

    Returns:
        The panel, or None when the run holds no such paragraph.
    """
    anchor = f"{PARAGRAPH_SCHEME}{number}"
    for unit in (state.get("units", {}) or {}).values():
        if unit["anchor"] != anchor:
            continue
        source = (state.get("sources", {}) or {}).get(unit["source_id"], {})
        accounting = (state.get("accounting", {}) or {}).get(unit["source_id"], {})
        reasons = {u["anchor"]: u["reason"] for u in accounting.get("without_facts", [])}
        failed = any(
            not Fact.model_validate(c, context=FACT_CONTEXT).passed_checks
            for contents in (state.get("facts", {}) or {}).values()
            for c in contents
            if c["subject"]["anchor"] == anchor and c["subject"]["source_id"] == unit["source_id"]
        )
        left_out = (
            "A fact read from this paragraph failed a check, so the brief does not cite it."
            if failed
            else "The brief cites no fact from this paragraph."
        )
        return ParagraphPanel(
            place=f"Paragraph {number}",
            source_title=source.get("title", ""),
            digest=source.get("digest", ""),
            unit_text=(state.get("unit_text", {}) or {}).get(unit["id"], ""),
            reason=reasons.get(anchor, left_out),
        )
    return None
