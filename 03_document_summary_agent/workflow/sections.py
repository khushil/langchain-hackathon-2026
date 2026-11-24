"""The section step: one model call reads one section into the starter's ``SectionSummary``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from context.facts import read_section
from context.reader import SectionRead, read_document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from fsi_common.ids import digest_text
from sub_agent import INSTRUCTIONS, SectionSummary
from utils.models import ROLE_MODELS
from utils.state import fact_writes
from workflow.checks import run_check
from workflow.engine_state import SectionTask
from workflow.errors import SectionCallError

ModelSource = Callable[[str], BaseChatModel]
"""Gives the chat model for a role; ``get_model`` in production, a scripted fake in tests."""

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
    chat = models("section").with_structured_output(SectionSummary)
    reply = chat.invoke([SystemMessage(INSTRUCTIONS), HumanMessage(section_task(section))])
    if isinstance(reply, SectionSummary):
        return reply
    try:
        return SectionSummary.model_validate(reply)
    except ValueError as exc:
        raise SectionCallError(
            f"The model's reply for section {section.number} is not a section summary: {exc}"
        ) from exc


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
        summary = call_section_model(models, section)
        read = read_section(
            summary,
            section=section,
            source=document.source,
            model=ROLE_MODELS["section"].model,
            prompt_version=SECTION_PROMPT_VERSION,
        )
        failed = [f for f in read.facts.values() if not f.passed_checks]
        subject = f"section:{section.number}"
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
        }
        return {
            "section_results": {section.number: read.result.model_dump(mode="json")},
            "raw_summaries": {section.number: summary.model_dump(mode="json")},
            "facts": fact_writes(read.facts.values()),
            "open_questions": {q.id: q.to_json() for q in read.questions},
            "check_results": checks,
        }

    return section_step
