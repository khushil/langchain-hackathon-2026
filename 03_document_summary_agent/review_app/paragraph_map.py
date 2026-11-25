"""The picture of the document: its paragraphs in order, each marked by what was found in it.

It is drawn from the state of the run: the units the document was read into, the unit accounting,
the facts and their checks, and the open questions. Every paragraph read is in it once, and
the count beside it says how many of the paragraphs read are accounted for.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from fsi_common.records import Decision, Fact, SignOff
from review_app.source_view import decision_line, kind_label
from utils.records import FACT_CONTEXT

FAILED = "failed"
QUESTION = "question"
SETTLED = "settled"
OBLIGATION = "obligation"
OTHER = "other"
NOTHING = "nothing"
PARAGRAPH_SCHEME = "para:"
SETTLED_WORD = "Question settled"
KEY_WORDS = (
    (FAILED, "Failed check"),
    (QUESTION, "Open question"),
    (SETTLED, SETTLED_WORD),
    (OBLIGATION, "Obligation"),
    (OTHER, "Other fact"),
    (NOTHING, "No fact"),
)
"""The kinds of mark in the order the key lists them, each with the word the key gives it."""
NO_OBLIGATION_FOUND = "No obligation was found in this paragraph."
_NO_FACT = re.compile(r"^The section reader found no obligation in this paragraph\.?$")
_MARKED = re.compile(
    r'^The paragraph contains "(?P<marker>[^"]+)", which marks an obligation, and none was read '
    r"from it, even on a second read of the paragraph alone; it is an open question for the "
    r"reviewer\.?$"
)


def plain_reason(reason: str) -> str:
    """Say why a paragraph gave no fact in the words a reviewer uses.

    Args:
        reason: The reason the run recorded for the paragraph.

    Returns:
        The reason without any account of how the run reads, and the reason itself when it holds
        none.
    """
    if _NO_FACT.match(reason):
        return NO_OBLIGATION_FOUND
    marked = _MARKED.match(reason)
    if marked:
        return (
            f'The paragraph contains "{marked["marker"]}", which can mark an obligation, but no '
            "obligation was recorded from it. A question about it is open."
        )
    return reason


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
    def key(self) -> tuple[tuple[str, str], ...]:
        """The marks the picture uses, each with its word, so a reader can tell them apart."""
        used = {cell.finding.kind for section in self.sections for cell in section.cells}
        return tuple((kind, word) for kind, word in KEY_WORDS if kind in used)

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


def _settled_detail(asked: Sequence[Mapping], settled: Mapping[str, str]) -> str:
    return "; ".join(f"{SETTLED_WORD}: {settled[q['id']]}" for q in asked)


def _finding(
    facts: Sequence[Fact],
    questions: Sequence[Mapping],
    reason: str | None,
    settled: Mapping[str, str],
) -> Finding:
    waiting = [q for q in questions if q["id"] not in settled]
    done = [q for q in questions if q["id"] in settled]
    if not facts and waiting:
        return Finding(
            QUESTION, "Open question", plain_reason(reason) if reason else "A question is open."
        )
    if not facts and done:
        return Finding(SETTLED, SETTLED_WORD, _settled_detail(done, settled))
    if not facts:
        return Finding(
            NOTHING,
            "No fact",
            plain_reason(reason) if reason else "No fact was read from this paragraph.",
        )
    found = []
    failed = [f for f in facts if not f.passed_checks]
    obligations = [f for f in facts if f.kind == "obligation"]
    if failed:
        found.append(("Failed check", FAILED, "Failed check"))
    if waiting:
        found.append(("Open question", QUESTION, "Open question"))
    if done:
        found.append((SETTLED_WORD, SETTLED, _settled_detail(done, settled)))
    if obligations:
        deadline = any(f.attributes.get("deadline") for f in obligations)
        word = "Obligation, deadline" if deadline else "Obligation"
        found.append((word, OBLIGATION, word))
    kinds = dict.fromkeys(kind_label(f.kind) for f in facts if f.kind != "obligation")
    found += [(k, OTHER, k) for k in kinds]
    word, kind, _ = found[0]
    return Finding(kind, word, "; ".join(detail for _, _, detail in found))


def build_map(
    state: Mapping,
    *,
    sections: Sequence[str] | None,
    titles: Mapping[str, str],
    href_for: Callable[[str, Sequence[str]], str],
    current: str | None = None,
    settled: Mapping[str, str] | None = None,
) -> DocumentMap | None:
    """Draw the document's paragraphs from a run's state.

    Args:
        state: The run's state: sources, facts, open questions and the unit accounting.
        sections: The sections the run was asked to read, or None for every section.
        titles: Each section's title by number.
        href_for: Gives the address that opens a paragraph, from its anchor and the ids of the
            facts read from it.
        current: The anchor of the paragraph open now, if any.
        settled: How each question that a person has settled was settled, by question id, in
            words. A question not in it is drawn as open.

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
        finding = _finding(held, asked, without.get(anchor), settled or {})
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
            reason=plain_reason(reasons[anchor]) if anchor in reasons else left_out,
        )
    return None


def settled_by_state(state: Mapping) -> dict[str, str]:
    """Say how each question of a finished run was settled, from the decisions it holds.

    Args:
        state: The state of a signed or returned run.

    Returns:
        For each question answered by a decision or accepted as an assumption in the sign-off, a
        sentence such as ``Answered by Dana Whitfield, Head of Compliance, on 24 November 2026``.
    """
    questions = set(state.get("open_questions", {}) or {})
    found: dict[str, str] = {}
    for raw in (state.get("decisions", {}) or {}).values():
        decision = Decision.model_validate(raw)
        if decision.outcome == "answer" and decision.subject_id in questions:
            found[decision.subject_id] = decision_line(decision)
    held = state.get("sign_off")
    if held:
        for assumption in SignOff.model_validate(held).assumptions:
            if assumption.question_id in questions:
                found.setdefault(assumption.question_id, "Accepted as an assumption")
    return found
