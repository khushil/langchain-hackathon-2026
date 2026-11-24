"""This topic's fact kinds and section results, and converters to and from the starter's shapes.

The starter's ``Obligation`` and ``SectionSummary`` are what the section sub-agent is asked to
return. Each converts into the shared records and back with every field kept, so the sub-agent's
format stays the starter's and everything after it works on cited facts. They are imported from
``sub_agent`` only when a conversion back needs them, because importing ``sub_agent`` chooses the
section model.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import Field, ValidationError

from fsi_common.records import CheckResult, Extractor, Fact, Source, fact_kinds_context
from fsi_common.records.base import FactId, NonBlank, Part

if TYPE_CHECKING:
    from sub_agent import Obligation, SectionSummary

DOCUMENT_FACT_KINDS = (
    "obligation",
    "permission",
    "guidance",
    "definition",
    "scope",
    "effective_date",
    "regulator_action",
    "context",
    "firm_attribute",
    "provider_attribute",
)
"""The closed list of fact kinds for this topic: the reference labels' eight kinds of paragraph
item, and the two kinds of fact read from the firm and provider tables."""

FACT_KINDS = fact_kinds_context(DOCUMENT_FACT_KINDS)
"""The validation context that holds the list, for ``Fact.build`` and ``Fact.model_validate``."""

PARAGRAPH_SCHEME = "para"


class StarterShapeError(Exception):
    """An item in the starter's shape cannot become a cited fact, or a fact cannot go back."""


class SectionResult(Part):
    """What one section's sub-agent returned, beside the facts it produced.

    ``fact_ids`` keeps the order of the obligations, and an obligation given twice appears twice,
    so the starter's ``SectionSummary`` comes back unchanged.
    """

    number: NonBlank = Field(description="The section number, for example '7'")
    title: NonBlank = Field(description="The section title")
    summary: str = Field(description="The sub-agent's one to three sentences on the section")
    fact_ids: list[FactId] = Field(
        description="The section's obligation facts, in the order returned"
    )


@dataclass(frozen=True)
class SectionRecords:
    """One section's result and its facts, by id."""

    result: SectionResult
    facts: dict[str, Fact]


def paragraph_anchor(paragraph: str) -> str:
    """Return the anchor of a paragraph number.

    Args:
        paragraph: The number as the document writes it, for example ``7.1``.

    Returns:
        ``para:7.1``.
    """
    return f"{PARAGRAPH_SCHEME}:{paragraph}"


def obligation_to_fact(
    obligation: Obligation,
    *,
    source: Source,
    extractor: Extractor,
    model: str | None,
    prompt_version: str | None,
    checks: Sequence[CheckResult],
) -> Fact:
    """Turn one starter ``Obligation`` into a cited fact.

    Args:
        obligation: The obligation as the sub-agent returned it.
        source: The document it was read from.
        extractor: The step that produced it.
        model: The model that produced it, or None for code.
        prompt_version: The prompt's version, or None for code.
        checks: The plain-code checks already run on it, one or more.

    Returns:
        A fact of kind ``obligation`` about the obligation's paragraph, quoting its evidence.

    Raises:
        StarterShapeError: If the obligation cannot be a valid fact (no quote, a paragraph that is
            not one number, no checks); the message names the paragraph.
    """
    anchor = paragraph_anchor(obligation.paragraph)
    try:
        return Fact.build(
            context=FACT_KINDS,
            kind="obligation",
            subject={"source_id": source.id, "anchor": anchor},
            quote=obligation.evidence,
            attributes={"requirement": obligation.requirement, "deadline": obligation.deadline},
            status={"status": "documented"},
            provenance={
                "source_id": source.id,
                "anchor": anchor,
                "extractor": extractor,
                "model": model,
                "prompt_version": prompt_version,
                "as_of": source.digest,
            },
            checks=list(checks),
        )
    except ValidationError as exc:
        raise StarterShapeError(
            f"The obligation from paragraph '{obligation.paragraph}' cannot be a cited fact: {exc}"
        ) from exc


def fact_to_obligation(fact: Fact) -> Obligation:
    """Turn an obligation fact back into the starter's ``Obligation``.

    Args:
        fact: A fact of kind ``obligation`` anchored on a paragraph.

    Returns:
        The obligation, with the fact's requirement, paragraph, deadline and quote.

    Raises:
        StarterShapeError: If the fact is not an obligation on a paragraph or lacks a requirement.
    """
    from sub_agent import Obligation

    scheme, _, paragraph = fact.subject.anchor.partition(":")
    requirement = fact.attributes.get("requirement")
    deadline = fact.attributes.get("deadline")
    if fact.kind != "obligation" or scheme != PARAGRAPH_SCHEME or not isinstance(requirement, str):
        raise StarterShapeError(
            f"Fact {fact.id} is not an obligation on a paragraph with a requirement."
        )
    if deadline is not None and not isinstance(deadline, str):
        raise StarterShapeError(f"Fact {fact.id} has a deadline that is not text.")
    return Obligation(
        requirement=requirement, paragraph=paragraph, deadline=deadline, evidence=fact.quote
    )


def section_summary_to_records(
    summary: SectionSummary,
    *,
    source: Source,
    extractor: Extractor,
    model: str | None,
    prompt_version: str | None,
    checks_for: Callable[[Obligation], Sequence[CheckResult]],
) -> SectionRecords:
    """Turn one starter ``SectionSummary`` into a section result and its facts.

    Args:
        summary: The section summary as the sub-agent returned it.
        source: The document it was read from.
        extractor: The step that produced it.
        model: The model that produced it.
        prompt_version: The prompt's version.
        checks_for: Runs the plain-code checks on one obligation and returns their results.

    Returns:
        The section result and its facts by id.

    Raises:
        StarterShapeError: If any obligation cannot be a valid fact; the message names it.
    """
    facts = [
        obligation_to_fact(
            obligation,
            source=source,
            extractor=extractor,
            model=model,
            prompt_version=prompt_version,
            checks=checks_for(obligation),
        )
        for obligation in summary.obligations
    ]
    result = SectionResult(
        number=summary.number,
        title=summary.title,
        summary=summary.summary,
        fact_ids=[fact.id for fact in facts],
    )
    return SectionRecords(result=result, facts={fact.id: fact for fact in facts})


def records_to_section_summary(result: SectionResult, facts: Mapping[str, Fact]) -> SectionSummary:
    """Turn a section result and its facts back into the starter's ``SectionSummary``.

    Args:
        result: The section result.
        facts: Facts by id, holding at least every id the result lists.

    Returns:
        The section summary, with the obligations in their original order.

    Raises:
        StarterShapeError: If a listed fact is missing; nothing is skipped.
    """
    from sub_agent import SectionSummary

    missing = [fact_id for fact_id in result.fact_ids if fact_id not in facts]
    if missing:
        raise StarterShapeError(
            f"Section {result.number} lists facts that are not held: {', '.join(missing)}"
        )
    return SectionSummary(
        number=result.number,
        title=result.title,
        summary=result.summary,
        obligations=[fact_to_obligation(facts[fact_id]) for fact_id in result.fact_ids],
    )
