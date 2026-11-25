"""The marker check: a paragraph with an obligation marker is never closed as holding none."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from context.facts import ASK_ROLE
from context.markers import MARKERS, marker_in
from context.reader import Paragraph, paragraph_unit
from fsi_common.records import Fact, OpenQuestion, Source

MARKED_REASON = "ambiguous_meaning"
"""The reason of the open question about a marked paragraph that gave no obligation."""


@dataclass(frozen=True)
class MarkedParagraph:
    """A paragraph that holds an obligation marker, and the first marker it holds."""

    paragraph: Paragraph
    marker: str


def _obligation_anchors(facts: Iterable[Fact]) -> set[str]:
    return {
        fact.subject.anchor for fact in facts if fact.kind == "obligation" and fact.passed_checks
    }


def marked_without_obligation(
    paragraphs: Iterable[Paragraph], facts: Iterable[Fact]
) -> list[MarkedParagraph]:
    """Find the paragraphs that hold an obligation marker and have no obligation fact.

    A paragraph holds an obligation only when an obligation fact on it passed every check. A fact
    that failed a check stays on the record, but the brief does not cite it, so the paragraph is
    treated as having none until a person has been asked.

    Args:
        paragraphs: The paragraphs to look at, for example those of one section.
        facts: The facts read; only obligation facts that passed every check count, and only at a
            paragraph's anchor.

    Returns:
        The paragraphs found, each with its marker, in the order the paragraphs were given.
    """
    held = _obligation_anchors(facts)
    found = []
    for paragraph in paragraphs:
        marker = marker_in(paragraph.text)
        if marker is not None and paragraph.anchor not in held:
            found.append(MarkedParagraph(paragraph=paragraph, marker=marker))
    return found


def unconfirmed_questions(
    marked: Sequence[MarkedParagraph], *, source: Source
) -> list[OpenQuestion]:
    """Ask the reviewer about each marked paragraph that gave no obligation on a second read.

    Args:
        marked: The paragraphs that still have no passing obligation fact after their second
            read.
        source: The document the paragraphs are from.

    Returns:
        One open question for each, naming the paragraph and the marker and resting on the
        paragraph's unit.
    """
    questions = []
    for found in marked:
        number, marker = found.paragraph.number, found.marker
        questions.append(
            OpenQuestion.build(
                about={"source_id": source.id, "anchor": found.paragraph.anchor},
                question=(
                    f'Paragraph {number} of {source.key} contains "{marker}", which can mark an '
                    "obligation, and no obligation that passed its checks was read from it, even "
                    f"when the paragraph was read again on its own. Does paragraph {number} place "
                    "an obligation on the firm, and if so what is it?"
                ),
                why_unknown=(
                    f'Paragraph {number} contains "{marker}", which usually marks a duty. No '
                    f"obligation that passed its checks was read from it in section "
                    f"{found.paragraph.section}, and none was read when paragraph {number} was "
                    "read again on its own."
                ),
                impact=(
                    "If the paragraph places an obligation on the firm, the brief leaves it out "
                    "until it is added; if it places none, nothing changes."
                ),
                ask_role=ASK_ROLE,
                reason=MARKED_REASON,
                cites=[paragraph_unit(source, found.paragraph).id],
                priority="high",
                state="open",
            )
        )
    return questions


def unmarked_obligation_questions(
    paragraphs: Iterable[Paragraph], facts: Iterable[Fact], *, source: Source
) -> list[OpenQuestion]:
    """Ask the reviewer about each paragraph with no marker that gave an obligation fact.

    The facts stay on the record and in the brief; the question only asks whether the paragraph
    places an obligation on the firm. One paragraph gives one question, however many facts were
    read from it, and the question rests on all of them.

    Args:
        paragraphs: The paragraphs whose facts are looked at, for example those of one section.
        facts: The facts read.
        source: The document the paragraphs are from.

    Returns:
        One open question for each such paragraph, in the order its first fact came, resting on
        every obligation fact read from it.
    """
    unmarked = {p.anchor: p for p in paragraphs if marker_in(p.text) is None}
    read: dict[str, list[Fact]] = {}
    for fact in facts:
        if fact.kind == "obligation" and fact.subject.anchor in unmarked:
            held = read.setdefault(fact.subject.anchor, [])
            if all(fact.id != other.id for other in held):
                held.append(fact)
    listed = ", ".join(f'"{marker}"' for marker in MARKERS)
    questions = []
    for anchor, held in read.items():
        number = unmarked[anchor].number
        quotes = " and ".join(f'"{fact.quote}"' for fact in held)
        quote_words = "The quote is" if len(held) == 1 else "The quotes are"
        questions.append(
            OpenQuestion.build(
                about={"source_id": source.id, "anchor": anchor},
                question=(
                    f"An obligation was read from paragraph {number} of {source.key}, which holds "
                    f"none of the words that mark an obligation. {quote_words} {quotes}. "
                    f"Does paragraph {number} place an obligation on the firm?"
                ),
                why_unknown=(
                    f"An obligation was read from paragraph {number}, but the paragraph has none "
                    f"of {listed}, the words that usually mark a duty, so the obligation rests on "
                    "how the paragraph was understood and not on its wording."
                ),
                impact=(
                    "The facts stay on the record, and the brief cites each only if it passed its "
                    "checks. If the paragraph places no obligation on the firm, a brief that "
                    "cites one states a duty the document does not impose."
                    if len(held) > 1
                    else "The fact stays on the record, and the brief cites it only if it passed "
                    "its checks. If the paragraph places no obligation on the firm, a brief that "
                    "cites the fact states a duty the document does not impose."
                ),
                ask_role=ASK_ROLE,
                reason="inferred_only",
                cites=[fact.id for fact in held],
                priority="medium",
                state="open",
            )
        )
    return questions
