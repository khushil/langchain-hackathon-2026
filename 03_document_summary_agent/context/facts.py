"""Turn one section's result into checked facts and open questions."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from context.checks import checks_for
from context.errors import SectionReadError
from context.reader import SectionRead, paragraph_unit
from fsi_common.records import CheckResult, Extractor, Fact, OpenQuestion, Source
from sub_agent import Obligation, SectionSummary
from utils.records import (
    SectionResult,
    StarterShapeError,
    paragraph_anchor,
    section_summary_to_records,
)

SECTION_READER = Extractor(name="section-reader", version="0.1.0")
"""The step that reads one section into obligation facts, with a model."""

LABEL_CHECK = "section-label.v1"
COUNT_CHECK = "section-read.v1"
ASK_ROLE = "Head of Compliance"


@dataclass(frozen=True)
class SectionFacts:
    """What one section's result became: its result record, its facts and its open questions.

    ``count_check`` states whether every obligation read on a paragraph of the section is held by
    a fact as a requirement, and names the paragraphs where the counts differ.
    """

    result: SectionResult
    facts: dict[str, Fact]
    questions: list[OpenQuestion]
    label_check: CheckResult
    count_check: CheckResult


def requirement_mismatches(
    obligations: Sequence[Obligation], facts: Mapping[str, Fact]
) -> list[str]:
    """Name the paragraphs whose obligations and recorded requirements differ in number.

    Args:
        obligations: The obligations read, each on a paragraph the section has.
        facts: The facts the read produced, by id.

    Returns:
        The paragraph numbers where the obligations given and the requirements the facts hold
        are not the same count, in order of first appearance; empty when every one is held.
    """
    given = Counter(o.paragraph for o in obligations)
    held: Counter[str] = Counter()
    for fact in facts.values():
        requirement = fact.attributes.get("requirement")
        count = len(requirement) if isinstance(requirement, list) else 0
        held[fact.subject.anchor.partition(":")[2]] += count
    paragraphs = list(dict.fromkeys([*given, *held]))
    return [p for p in paragraphs if given[p] != held[p]]


def _unresolved_questions(
    unresolved: Sequence[Obligation], *, section: SectionRead, source: Source
) -> list[OpenQuestion]:
    """One open question for each paragraph the section does not have that a model cited."""
    by_paragraph: dict[str, list[str]] = {}
    for obligation in unresolved:
        evidence = by_paragraph.setdefault(obligation.paragraph, [])
        if obligation.evidence not in evidence:
            evidence.append(obligation.evidence)
    first, last = section.paragraphs[0].number, section.paragraphs[-1].number
    cites = sorted(paragraph_unit(source, p).id for p in section.paragraphs)
    questions = []
    for number, evidence in sorted(by_paragraph.items()):
        anchor = paragraph_anchor(number)
        valid = re.fullmatch(r"[a-z][a-z0-9_]*:\S+", anchor) is not None
        quoted = "; ".join(f'"{text}"' for text in evidence)
        questions.append(
            OpenQuestion.build(
                about={
                    "source_id": source.id,
                    "anchor": anchor if valid else section.paragraphs[0].anchor,
                },
                question=(
                    f"Section {section.number} was read and an obligation was said to come from "
                    f"paragraph {number}, which section {section.number} does not have. The "
                    f"evidence given was {quoted}. Which paragraph is meant?"
                ),
                why_unknown=(
                    f"The section reader cited paragraph {number}; the paragraphs of section "
                    f"{section.number} are {first} to {last}, and none is {number}."
                ),
                impact="The obligation is not a fact, because a fact needs a paragraph to cite, "
                "so the brief leaves it out until the paragraph is known.",
                ask_role=ASK_ROLE,
                reason="unresolved_reference",
                cites=cites,
                priority="medium",
                state="open",
            )
        )
    return questions


def read_section(
    summary: SectionSummary,
    *,
    section: SectionRead,
    source: Source,
    model: str,
    prompt_version: str,
) -> SectionFacts:
    """Turn a section sub-agent's ``SectionSummary`` into checked facts and open questions.

    Each obligation on a paragraph of the section becomes a fact with its quote check and, when
    it has a deadline, its deadline check. Obligations that share a paragraph, quote and deadline
    are one fact holding every requirement given. A fact that fails stays on the record with the
    failed check. An obligation that cites a paragraph the section does not have is not a fact,
    because a fact needs a paragraph to cite: it stays in the raw summary the caller keeps, and
    gives an open question of reason ``unresolved_reference``, one for each such paragraph.

    Args:
        summary: The section summary as the model returned it.
        section: The section as read, whose number and title the records use.
        source: The document the section is from.
        model: The model that produced the summary.
        prompt_version: The version of the prompt it was asked with.

    Returns:
        The result, the facts by id, the questions, the check on the section's label and the check
        on the count of requirements.

    Raises:
        SectionReadError: If an obligation on a paragraph of the section cannot be a fact (a
            blank quote); the message names the section and the paragraph.
    """
    by_number = {p.number: p.text for p in section.paragraphs}
    resolved = [o for o in summary.obligations if o.paragraph in by_number]
    unresolved = [o for o in summary.obligations if o.paragraph not in by_number]

    def checks_for_obligation(obligation: Obligation) -> list[CheckResult]:
        return checks_for(obligation, by_number[obligation.paragraph])

    labelled = summary.model_copy(
        update={"number": section.number, "title": section.title, "obligations": resolved}
    )
    try:
        records = section_summary_to_records(
            labelled,
            source=source,
            extractor=SECTION_READER,
            model=model,
            prompt_version=prompt_version,
            checks_for=checks_for_obligation,
        )
    except StarterShapeError as exc:
        raise SectionReadError(
            f"Section {section.number} cannot be read into facts. {exc}"
        ) from exc
    same = (summary.number, summary.title) == (section.number, section.title)
    label_check = CheckResult(
        check=LABEL_CHECK,
        outcome="pass" if same else "fail",
        detail=(
            f"the model labelled the section {summary.number} '{summary.title}'; "
            f"the section as read is {section.number} '{section.title}'"
        ),
    )
    differing = requirement_mismatches(resolved, records.facts)
    held = sum(len(f.attributes["requirement"]) for f in records.facts.values())
    detail = (
        f"{held} of {len(resolved)} obligations of section {section.number} are held as "
        f"requirements of {len(records.facts)} distinct facts; "
        f"{len(unresolved)} cite a paragraph the section does not have and are open questions"
    )
    if differing:
        detail += f"; the counts differ on paragraph(s) {', '.join(differing)}"
    count_check = CheckResult(
        check=COUNT_CHECK, outcome="fail" if differing else "pass", detail=detail
    )
    return SectionFacts(
        result=records.result,
        facts=records.facts,
        questions=_unresolved_questions(unresolved, section=section, source=source),
        label_check=label_check,
        count_check=count_check,
    )
