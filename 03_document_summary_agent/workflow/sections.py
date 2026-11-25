"""The section step: one model call reads one section into the starter's ``SectionSummary``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from context.facts import SectionFacts, read_section
from context.marker_check import (
    marked_without_obligation,
    unconfirmed_questions,
    unmarked_obligation_questions,
)
from context.markers import marker_in
from context.reader import SectionRead, read_document
from fsi_common.ids import digest_text
from fsi_common.records import OpenQuestion, Source
from sub_agent import INSTRUCTIONS, SectionSummary
from utils.models import ROLE_MODELS
from utils.state import fact_writes
from workflow.checks import run_check
from workflow.engine_state import SectionTask
from workflow.errors import SectionCallError
from workflow.second_read import read_again, second_read_records

ModelSource = Callable[[str], BaseChatModel]
"""Gives the chat model for a role; ``get_model`` in production, a scripted fake in tests."""

MARKER_CHECK = "marker-check.v1"
"""The run check that states the second reads and the questions the obligation markers raised."""

SECTION_PROMPT_VERSION = f"section-{digest_text(INSTRUCTIONS)[7:15]}"
"""The prompt's version, taken from the digest of the starter's sub-agent instructions."""


def section_task(section: SectionRead) -> str:
    """Return the task text a section's model call is given.

    Args:
        section: The section, with its number, title and full text.

    Returns:
        The number, title and text, as the starter's orchestrator passes them to a sub-agent.
    """
    return f"Number: {section.number}\nTitle: {section.title}\n\nText:\n{section.text}"


def ask_section_model(models: ModelSource, task: str, *, where: str) -> SectionSummary:
    """Ask the section model for a summary of one task text.

    Args:
        models: Gives the chat model for a role.
        task: The task text: a section, or one paragraph's second read.
        where: What is read, for an error, for example ``section 7``.

    Returns:
        The summary the model returned.

    Raises:
        SectionCallError: If the reply is not a section summary.
    """
    chat = models("section").with_structured_output(SectionSummary)
    reply = chat.invoke([SystemMessage(INSTRUCTIONS), HumanMessage(task)])
    if isinstance(reply, SectionSummary):
        return reply
    try:
        return SectionSummary.model_validate(reply)
    except ValueError as exc:
        raise SectionCallError(
            f"The model's reply for {where} is not a section summary: {exc}"
        ) from exc


def call_section_model(models: ModelSource, section: SectionRead) -> SectionSummary:
    """Ask the section model for one section's summary.

    Args:
        models: Gives the chat model for a role.
        section: The section to read.

    Returns:
        The summary the model returned.

    Raises:
        SectionCallError: If the reply is not a section summary.
    """
    return ask_section_model(models, section_task(section), where=f"section {section.number}")


@dataclass(frozen=True)
class SectionReading:
    """A section as read: its facts and questions, and the summary the facts came from."""

    facts: SectionFacts
    summary: SectionSummary
    questions: list[OpenQuestion]
    reread: list[str]
    marked_total: int
    second_reads: dict[str, dict[str, Any]]
    asked: int
    unmarked: int


def read_section_checked(
    models: ModelSource, section: SectionRead, *, source: Source, summary: SectionSummary
) -> SectionReading:
    """Read a section's summary into facts, and run the marker check on them.

    A paragraph that holds an obligation marker and has no obligation fact is read once more,
    alone, with the same model role; what that read returns joins the section's obligations and
    meets the same checks. A paragraph still without an obligation fact becomes an open question
    naming the marker. An obligation fact on a paragraph with no marker is kept and asked about.

    Args:
        models: Gives the chat model for a role.
        section: The section.
        source: The document it is from.
        summary: The first read of the section, as the model returned it.

    Returns:
        The reading: facts, the questions, the first read's summary untouched, the record of each
        second read, the paragraphs read again, and the counts of questions raised by each half
        of the check.

    Raises:
        SectionCallError: If a second read's reply is not a section summary.
    """

    def read(from_summary: SectionSummary) -> SectionFacts:
        return read_section(
            from_summary,
            section=section,
            source=source,
            model=ROLE_MODELS["section"].model,
            prompt_version=SECTION_PROMPT_VERSION,
        )

    facts = read(summary)
    marked = marked_without_obligation(section.paragraphs, facts.facts.values())
    if marked:
        again = read_again(
            lambda task, where: ask_section_model(models, task, where=where), section, marked=marked
        )
        added = [o for second in again for o in second.summary.obligations]
        facts = read(summary.model_copy(update={"obligations": [*summary.obligations, *added]}))
    else:
        again = []
    still = marked_without_obligation(section.paragraphs, facts.facts.values())
    forward = unconfirmed_questions(still, source=source)
    reverse = unmarked_obligation_questions(section.paragraphs, facts.facts.values(), source=source)
    questions = [*facts.questions, *forward, *reverse]
    return SectionReading(
        facts=facts,
        summary=summary,
        questions=questions,
        second_reads=second_read_records(again, facts.facts, questions=questions),
        reread=[m.paragraph.number for m in marked],
        marked_total=sum(1 for p in section.paragraphs if marker_in(p.text)),
        asked=len(forward),
        unmarked=len(reverse),
    )


def make_section_step(models: ModelSource) -> Callable[[SectionTask], dict[str, Any]]:
    """Build the section step, which reads one section with the model ``models`` gives.

    Args:
        models: Gives the chat model for a role.

    Returns:
        The graph node for one section.
    """

    def section_step(task: SectionTask) -> dict[str, Any]:
        request = task["request"]
        document = read_document(request["document_id"])
        section = document.section(task["section"])
        if section is None:
            raise SectionCallError(f"The document has no section {task['section']}.")
        reading = read_section_checked(
            models,
            section,
            source=document.source,
            summary=call_section_model(models, section),
        )
        read = reading.facts
        failed = [f for f in read.facts.values() if not f.passed_checks]
        subject = f"section:{section.number}"
        names = f" ({', '.join(reading.reread)})" if reading.reread else ""
        checks = {
            **run_check(
                read.count_check.check,
                subject,
                passed=read.count_check.outcome == "pass",
                detail=f"{read.count_check.detail}; "
                f"{len(failed)} of {len(read.facts)} distinct facts failed a check",
            ),
            **run_check(
                read.label_check.check,
                subject,
                passed=read.label_check.outcome == "pass",
                detail=read.label_check.detail,
            ),
            **run_check(
                MARKER_CHECK,
                subject,
                passed=True,
                detail=f"{len(reading.reread)} of {reading.marked_total} paragraph(s) with an "
                f"obligation marker were read a second time{names}; "
                f"{reading.asked} remain open questions; {reading.unmarked} paragraph(s) "
                "with no marker that gave an obligation fact are open questions",
            ),
        }
        return {
            "section_results": {section.number: read.result.model_dump(mode="json")},
            "raw_summaries": {section.number: reading.summary.model_dump(mode="json")},
            "second_reads": reading.second_reads,
            "facts": fact_writes(read.facts.values()),
            "open_questions": {q.id: q.to_json() for q in reading.questions},
            "check_results": checks,
        }

    return section_step
