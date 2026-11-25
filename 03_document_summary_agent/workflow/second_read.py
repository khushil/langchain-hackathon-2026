"""The second read: a paragraph with a marker and no obligation fact is read again, alone."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from context.marker_check import MARKED_REASON, MarkedParagraph
from context.reader import SectionRead
from fsi_common.records import Fact, OpenQuestion
from sub_agent import SectionSummary

AskModel = Callable[[str, str], SectionSummary]
"""Asks the section model for a summary: the task text, and where it is asked, for an error."""


def second_read_task(section: SectionRead, found: MarkedParagraph) -> str:
    """Return the task text of one paragraph's second read.

    It has the shape of a section's task (number, title, text) with the paragraph alone as the
    text, then the request. The request says why the paragraph is read again, so the model is not
    left to guess, and asks for the obligations the paragraph places on a firm, or none.

    Args:
        section: The section the paragraph is in, whose number and title are given.
        found: The paragraph and the marker the plain-code check found in it.

    Returns:
        The task text.
    """
    number = found.paragraph.number
    return (
        f"Number: {section.number}\nTitle: {section.title}\n\n"
        f"Text:\n{number} {found.paragraph.text}\n\n"
        f"Second read of paragraph {number} alone. A plain-code check found the word "
        f'"{found.marker}" in it, which can mark an obligation, and the first read of the section '
        "gave no obligation from it that passed its checks. Return every obligation paragraph "
        f"{number} places on a firm, citing paragraph {number}, or none if it places none."
    )


@dataclass(frozen=True)
class SecondRead:
    """One paragraph's second read: what was asked and what the model returned."""

    found: MarkedParagraph
    task: str
    summary: SectionSummary


def read_again(
    ask: AskModel, section: SectionRead, *, marked: Sequence[MarkedParagraph]
) -> list[SecondRead]:
    """Read each marked paragraph a second time, once, and return what each read gave.

    The paragraphs are read one after another in the order given, so the calls are the same
    whatever the timing of the replies. The obligations a read returned are passed on by the
    caller as the model gave them, to meet the same checks as any other.

    Args:
        ask: Asks the section model for a summary.
        section: The section the paragraphs are in.
        marked: The paragraphs to read again, each once.

    Returns:
        One record for each paragraph, in the order given.

    Raises:
        SectionCallError: If a reply is not a section summary; the paragraph is named.
    """
    reads = []
    for found in marked:
        task = second_read_task(section, found)
        summary = ask(task, f"paragraph {found.paragraph.number} (second read)")
        reads.append(SecondRead(found=found, task=task, summary=summary))
    return reads


def second_read_records(
    reads: Sequence[SecondRead],
    facts: Mapping[str, Fact],
    *,
    questions: Sequence[OpenQuestion],
) -> dict[str, dict[str, Any]]:
    """Record each second read, by paragraph anchor, with what it gave.

    Args:
        reads: The second reads made.
        facts: The facts of the section after the reads, by id.
        questions: The open questions of the section.

    Returns:
        For each paragraph anchor (``para:9.3``): the section, the marker found, the task asked,
        the summary the model returned untouched, whether an obligation fact that passed its
        checks was read from the paragraph, the ids of the obligation facts on it (a failed one
        included), and the id of the open question that asks about the paragraph (None when a
        fact that passed was read).
    """
    records: dict[str, dict[str, Any]] = {}
    for read in reads:
        paragraph = read.found.paragraph
        found = [
            f
            for f in facts.values()
            if f.kind == "obligation" and f.subject.anchor == paragraph.anchor
        ]
        fact_ids = sorted(f.id for f in found)
        asked = [
            q.id
            for q in questions
            if q.about.anchor == paragraph.anchor and q.reason == MARKED_REASON
        ]
        records[paragraph.anchor] = {
            "section": paragraph.section,
            "marker": read.found.marker,
            "asked": read.task,
            "summary": read.summary.model_dump(mode="json"),
            "gave_obligation": any(f.passed_checks for f in found),
            "fact_ids": fact_ids,
            "open_question_id": asked[0] if asked else None,
        }
    return records
