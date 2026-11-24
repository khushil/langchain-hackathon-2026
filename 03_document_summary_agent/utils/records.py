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

from fsi_common.records import CheckResult, Extractor, Fact, Source, fact_topic_context
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

COPIED_ATTRIBUTES = ("deadline",)
"""The attributes this topic copies word for word from the document: the deadline as written.

With the kind, the paragraph and the quote they make a fact's id. The requirements are the model's
plain wording of the paragraph, so they stay out of the id: a rerun that words one differently is
the same fact, and a changed quote or deadline is another."""

FACT_CONTEXT = fact_topic_context(kinds=DOCUMENT_FACT_KINDS, copied_attributes=COPIED_ATTRIBUTES)
"""The validation context that holds the topic's declaration, which ``Fact.build`` and
``Fact.model_validate`` need for every fact of this topic."""

PARAGRAPH_SCHEME = "para"


class StarterShapeError(Exception):
    """An item in the starter's shape cannot become a cited fact, or a fact cannot go back."""


class SectionResult(Part):
    """What one section's sub-agent returned, beside the facts it produced.

    ``fact_ids`` lists a fact once for each obligation that became it, in the order the
    obligations were returned. Obligations of one read that share a quote and a deadline on one
    paragraph are one fact whose requirements are listed in that same order, so the starter's
    ``SectionSummary`` comes back unchanged.
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
    requirements: Sequence[str] | None = None,
) -> Fact:
    """Turn one starter ``Obligation`` into a cited fact.

    Args:
        obligation: The obligation as the sub-agent returned it.
        source: The document it was read from.
        extractor: The step that produced it.
        model: The model that produced it, or None for code.
        prompt_version: The prompt's version, or None for code.
        checks: The plain-code checks already run on it, one or more.
        requirements: Every requirement given for obligations that share this one's paragraph,
            quote and deadline, in the order returned; the obligation's own requirement alone
            when omitted.

    Returns:
        A fact of kind ``obligation`` about the obligation's paragraph, quoting its evidence,
        whose ``requirement`` attribute is a list of one or more requirements.

    Raises:
        StarterShapeError: If the obligation cannot be a valid fact (no quote, a paragraph that is
            not one number, no checks); the message names the paragraph.
    """
    anchor = paragraph_anchor(obligation.paragraph)
    try:
        return Fact.build(
            context=FACT_CONTEXT,
            kind="obligation",
            subject={"source_id": source.id, "anchor": anchor},
            quote=obligation.evidence,
            attributes={
                "requirement": list(requirements or [obligation.requirement]),
                "deadline": obligation.deadline,
            },
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


def fact_to_obligations(fact: Fact) -> list[Obligation]:
    """Turn an obligation fact back into the starter's ``Obligation`` items, one per requirement.

    Args:
        fact: A fact of kind ``obligation`` anchored on a paragraph.

    Returns:
        One obligation for each requirement the fact holds, in order, each with the fact's
        paragraph, deadline and quote.

    Raises:
        StarterShapeError: If the fact is not an obligation on a paragraph, or its requirement is
            not a list of one or more texts.
    """
    from sub_agent import Obligation

    scheme, _, paragraph = fact.subject.anchor.partition(":")
    requirements = fact.attributes.get("requirement")
    deadline = fact.attributes.get("deadline")
    if fact.kind != "obligation" or scheme != PARAGRAPH_SCHEME:
        raise StarterShapeError(f"Fact {fact.id} is not an obligation on a paragraph.")
    if (
        not isinstance(requirements, list)
        or not requirements
        or not all(isinstance(r, str) for r in requirements)
    ):
        raise StarterShapeError(
            f"Fact {fact.id} has a requirement that is not a list of one or more texts."
        )
    if deadline is not None and not isinstance(deadline, str):
        raise StarterShapeError(f"Fact {fact.id} has a deadline that is not text.")
    return [
        Obligation(requirement=r, paragraph=paragraph, deadline=deadline, evidence=fact.quote)
        for r in requirements
    ]


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
        The section result and its facts by id. Obligations that share a fact id (the same
        paragraph, quote and deadline) become one fact holding every requirement given, in the
        order returned, and the result lists that id once for each of them.

    Raises:
        StarterShapeError: If any obligation cannot be a valid fact; the message names it.
    """
    kwargs = {
        "source": source,
        "extractor": extractor,
        "model": model,
        "prompt_version": prompt_version,
    }
    firsts: dict[str, tuple[Obligation, Sequence[CheckResult]]] = {}
    requirements: dict[str, list[str]] = {}
    order: list[str] = []
    for obligation in summary.obligations:
        checks = checks_for(obligation)
        fact = obligation_to_fact(obligation, checks=checks, **kwargs)
        order.append(fact.id)
        firsts.setdefault(fact.id, (obligation, checks))
        requirements.setdefault(fact.id, []).append(obligation.requirement)
    facts = {
        fact_id: obligation_to_fact(
            obligation, checks=checks, requirements=requirements[fact_id], **kwargs
        )
        for fact_id, (obligation, checks) in firsts.items()
    }
    result = SectionResult(
        number=summary.number, title=summary.title, summary=summary.summary, fact_ids=order
    )
    return SectionRecords(result=result, facts=facts)


def records_to_section_summary(result: SectionResult, facts: Mapping[str, Fact]) -> SectionSummary:
    """Turn a section result and its facts back into the starter's ``SectionSummary``.

    Args:
        result: The section result.
        facts: Facts by id, holding at least every id the result lists.

    Returns:
        The section summary, with the obligations in their original order: each time a fact id
        is listed, the next requirement that fact holds.

    Raises:
        StarterShapeError: If a listed fact is missing, or is listed more often than it holds
            requirements; nothing is skipped.
    """
    from sub_agent import SectionSummary

    missing = [fact_id for fact_id in result.fact_ids if fact_id not in facts]
    if missing:
        raise StarterShapeError(
            f"Section {result.number} lists facts that are not held: {', '.join(missing)}"
        )
    held = {fact_id: fact_to_obligations(facts[fact_id]) for fact_id in set(result.fact_ids)}
    used: dict[str, int] = {}
    obligations = []
    for fact_id in result.fact_ids:
        index = used.get(fact_id, 0)
        if index >= len(held[fact_id]):
            raise StarterShapeError(
                f"Section {result.number} lists fact {fact_id} {result.fact_ids.count(fact_id)} "
                f"times, and it holds {len(held[fact_id])} requirement(s)."
            )
        obligations.append(held[fact_id][index])
        used[fact_id] = index + 1
    return SectionSummary(
        number=result.number,
        title=result.title,
        summary=result.summary,
        obligations=obligations,
    )
