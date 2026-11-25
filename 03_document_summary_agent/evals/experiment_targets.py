"""The two agents a LangSmith experiment runs on a dataset example, and the document wrapper.

Both take an example's inputs and return a section summary as JSON in the starter's
``SectionSummary`` shape, so the same measures score what each one delivers. The starter's agent is
its section sub-agent as the starter defines it; this repository's engine is its section step, the
first read with the obligation-marker check and any second read.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from context.reader import SectionRead, read_document
from fsi_common.records import Fact
from sub_agent import SectionSummary
from utils.records import fact_to_obligations
from workflow.sections import ModelSource, call_section_model, read_section_checked

Target = Callable[[Mapping[str, Any]], dict[str, Any]]
"""Takes an example's inputs and returns what the agent delivers, as JSON."""


class SectionTextDiffersError(Exception):
    """An example's section text is not the library's, so the agents would read different text."""


def _section_of(inputs: Mapping[str, Any]) -> tuple[Any, SectionRead]:
    """Find the library's section an example names, and check the example holds its text."""
    document_id, given = inputs["document_id"], inputs["section"]
    document = read_document(document_id)
    section = document.section(given["number"])
    if section is None:
        raise SectionTextDiffersError(f"{document_id} has no section {given['number']}.")
    if section.text != given["text"]:
        raise SectionTextDiffersError(
            f"The example's text of section {section.number} of {document_id} is not the text the "
            "library holds; upload the dataset again under a new name."
        )
    return document, section


def starter_section_target(models: ModelSource | None = None) -> Target:
    """Build the starter's agent: its section sub-agent, run on one section as the notebook runs it.

    The notebook wraps the sub-agent in a deep agent of its own, with the sub-agent's instructions
    and its ``SectionSummary`` as the response format, and gives it the task
    ``Section N: title`` and the section's text. This does the same, so the deep agent's own
    planning and file tools are part of what is measured.

    Args:
        models: Gives the chat model for a role; ``get_model`` when absent.

    Returns:
        A function from an example's inputs to the agent's ``SectionSummary`` as JSON.
    """
    from deepagents import create_deep_agent

    from sub_agent import INSTRUCTIONS

    if models is None:
        from utils.models import get_model as models
    agent = create_deep_agent(
        model=models("section"), system_prompt=INSTRUCTIONS, response_format=SectionSummary
    )

    def run(inputs: Mapping[str, Any]) -> dict[str, Any]:
        _, section = _section_of(inputs)
        task = f"Section {section.number}: {section.title}\n\n{section.text}"
        reply = agent.invoke({"messages": [{"role": "user", "content": task}]})
        return SectionSummary.model_validate(reply["structured_response"]).model_dump()

    return run


def engine_section_target(models: ModelSource) -> Target:
    """Build this repository's engine: its section step, run on one section.

    The section is read, any paragraph with an obligation marker and no obligation is read again,
    and plain code checks every quote and deadline. What the agent delivers is the obligations of
    the facts that passed every check, one for each requirement a fact holds.

    Args:
        models: Gives the chat model for a role; ``get_model`` in production.

    Returns:
        A function from an example's inputs to a ``SectionSummary`` as JSON.
    """

    def run(inputs: Mapping[str, Any]) -> dict[str, Any]:
        document, section = _section_of(inputs)
        first = call_section_model(models, section)
        reading = read_section_checked(models, section, source=document.source, summary=first)
        passed: list[Fact] = [
            f for f in reading.facts.facts.values() if f.kind == "obligation" and f.passed_checks
        ]
        delivered = SectionSummary(
            number=section.number,
            title=section.title,
            summary=first.summary,
            obligations=[o for fact in passed for o in fact_to_obligations(fact)],
        )
        return delivered.model_dump()

    return run


def document_target(section_target: Target) -> Target:
    """Build an agent for a whole document from one for a section.

    Args:
        section_target: An agent that reads one section.

    Returns:
        A function from the document example's inputs to ``{"sections": [...]}``, with every
        section of the document read in order.
    """

    def run(inputs: Mapping[str, Any]) -> dict[str, Any]:
        request = inputs["request"]
        document = read_document(request["document_id"])
        sections = [
            section_target(
                {
                    "document_id": request["document_id"],
                    "firm_id": request["firm_id"],
                    "section": {"number": s.number, "title": s.title, "text": s.text},
                }
            )
            for s in document.sections
        ]
        return {"sections": sections}

    return run
