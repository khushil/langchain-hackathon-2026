"""An application's proposal: what the checks settle, and what a person is asked."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from context.checks import check_proposal, check_quote
from context.extraction import ApplicantFacts
from context.reader import ListEntry
from context.readings import Readings
from context.rule import Proposed, decide
from context.screening import ASK_ROLE, NEAR_FLOOR, PairResult
from context.text import contains_word_for_word
from fsi_common.records import (
    Extractor,
    Fact,
    InferenceRule,
    MatchRate,
    OpenQuestion,
    Source,
    SourceUnit,
)
from utils.records import FACT_CONTEXT

PROPOSER = Extractor(name="kyc-proposal", version="0.1.0")
"""The step that proposes a risk level and a decision; code, so its facts name no model."""

SETTLED_MATCH_RATE = MatchRate(matched=13, population=13)
"""How often a proposal settled by the checks agrees with the starter's labels: 13 of the 13
applications it settles. ``evals`` recomputes it, and a test fails if it is no longer so."""

SETTLED_RULE = InferenceRule(
    id="settled-by-checks",
    version="1",
    statement=(
        "An application is settled by the checks when its name is established and either a "
        "sanctions entry matches it by exact name and date of birth, or no list entry has any "
        "likeness to the name or to a relation named in it."
    ),
    match_rate=SETTLED_MATCH_RATE,
)
SENTENCE_END = re.compile(r"(?<=[.!?])\s")
__all__ = ["ApplicationOutcome", "Proposed", "assess_application", "decide"]


@dataclass(frozen=True)
class ApplicationOutcome:
    """Everything one application became beyond its details: screenings, proposal, questions.

    ``reasons`` holds, for each screening that is no fact, why. ``readings`` holds the two
    readings of each question that has them, by question id.
    """

    customer_id: str
    proposal: Fact
    facts: list[Fact] = field(default_factory=list)
    questions: list[OpenQuestion] = field(default_factory=list)
    readings: dict[str, Readings] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)


def first_sentence(text: str) -> str:
    """Return the first sentence of an application, which a proposal quotes.

    Args:
        text: The application.

    Returns:
        The text up to its first sentence end, or all of it.
    """
    return SENTENCE_END.split(text.strip(), maxsplit=1)[0]


def _relation_question(
    read: ApplicantFacts,
    entries: Sequence[ListEntry],
    *,
    source: Source,
    unit: SourceUnit,
    text: str,
) -> tuple[OpenQuestion, Readings] | None:
    relation = read.applicant.relation
    if relation is None or relation.related_name is not None or relation.related_office is None:
        return None
    countries = [
        e
        for e in entries
        if e.list == "pep" and contains_word_for_word(e.detail.rpartition(", ")[2], text)
    ]
    same = [
        f"The application says the {relation.relation} holds public office, "
        f'"{relation.related_office}".'
    ]
    for entry in countries:
        same.append(f"The PEP list holds {entry.name} ({entry.detail}).")
    if not countries:
        same.append("The application's own words are all there is to go on.")
    different = [
        f"The application gives no name for the {relation.relation}, so no entry can be matched.",
        "Holding an office does not put a person on the list.",
    ]
    readings = Readings(
        same_label=f"The {relation.relation} is on a list",
        same=same,
        different_label=f"The {relation.relation} is not on a list",
        different=different,
    )
    cites = [relation.fact_id]
    question = OpenQuestion.build(
        about={"source_id": source.id, "anchor": unit.anchor},
        question=(
            f"The applicant ({read.applicant.customer_id}) says their {relation.relation} holds "
            f'public office, "{relation.related_office}", and gives no name. Who is the '
            f"{relation.relation}, and is that person on the sanctions or PEP list?"
        ),
        why_unknown=(
            f"The lists can only be searched by name, and the application gives none for the "
            f"{relation.relation}."
        ),
        impact=(
            f"If the {relation.relation} is on a list, the applicant is a close relation of a "
            "listed person and the application is high risk; if not, the relation raises no risk."
        ),
        ask_role=ASK_ROLE,
        reason="missing_data",
        cites=cites,
        priority="medium",
        state="open",
    )
    return question, readings


def _marker_words(marker: str, pairs: Sequence[PairResult]) -> str:
    """Say in words what an item the checks could not settle is."""
    if marker == "relation":
        return "a relation with no name"
    if marker.startswith("detail:"):
        return f"a {marker.removeprefix('detail:').replace('_', ' ')} that failed its check"
    if marker.startswith("question:"):
        return "a detail the reading did not give"
    return next(p.entry.name for p in pairs if p.anchor == marker)


def _basis(
    pairs: Sequence[PairResult],
    *,
    sanctions: PairResult | None,
    unsettled: Sequence[str],
    name_checked: bool,
) -> str:
    if sanctions is not None:
        return sanctions.fact.attributes["settled_by"]
    if not name_checked:
        return (
            "The applicant's name could not be checked against the application, so no screening "
            "was run. The proposal takes the cautious reading, high risk, until a person answers."
        )
    if not unsettled:
        best = max(pairs, key=lambda p: p.score or 0.0)
        return (
            f"No likeness to any of the {len(pairs)} list entries: the highest name score is "
            f"{best.score:.2f} against {best.entry.name}, below the floor of {NEAR_FLOOR:.2f}."
        )
    names = [_marker_words(marker, pairs) for marker in unsettled]
    noun = "item" if len(unsettled) == 1 else "items"
    return (
        f"The checks did not settle {len(unsettled)} {noun}: {', '.join(names)}. "
        "The proposal takes the cautious reading, high risk, until a person answers."
    )


def assess_application(
    read: ApplicantFacts,
    pairs: Sequence[PairResult],
    *,
    source: Source,
    unit: SourceUnit,
    text: str,
    entries: Sequence[ListEntry],
) -> ApplicationOutcome:
    """Settle or propose for one application from its reading and its screenings.

    Args:
        read: The application's reading, with its facts and its questions.
        pairs: Its screening against every list entry.
        source: The applications source.
        unit: The application's unit.
        text: The application's text.
        entries: The list entries, for the candidates a relation with no name might be.

    Returns:
        The screening facts, the proposal fact, the questions with their readings, and the reason
        for every screening that is no fact.
    """
    applicant = read.applicant
    sanctions = next((p for p in pairs if p.settles), None)
    facts = [p.fact for p in pairs if p.fact is not None]
    reasons = {p.anchor: p.reason for p in pairs if p.fact is None}
    questions = list(read.questions)
    readings: dict[str, Readings] = {}
    unsettled: list[str] = []
    if sanctions is None:
        for pair in pairs:
            if pair.question is not None:
                questions.append(pair.question)
                readings[pair.question.id] = pair.readings
                unsettled.append(pair.anchor)
        unsettled += [
            f"detail:{kind}"
            for kind in dict.fromkeys(f.kind for f in read.facts if not f.passed_checks)
        ]
        unsettled += [q.id for q in read.questions]
        asked = _relation_question(read, entries, source=source, unit=unit, text=text)
        if asked is not None:
            questions.append(asked[0])
            readings[asked[0].id] = asked[1]
            unsettled.append("relation")
    name_checked = applicant.name is not None
    match = sanctions.entry.name if sanctions is not None else None
    result = decide(name_checked=name_checked, sanctions_match=match, unsettled=unsettled)
    basis = _basis(pairs, sanctions=sanctions, unsettled=unsettled, name_checked=name_checked)
    attributes = {
        "risk_level": result.risk_level,
        "decision": result.decision,
        "settled": result.settled,
        "basis": basis,
        "sanctions_match": match,
        "unsettled": unsettled,
        "name_checked": name_checked,
    }
    quote = first_sentence(text)
    status = (
        {"status": "inferred", "rule": SETTLED_RULE}
        if result.settled
        else {"status": "unknown", "unknown_reason": basis}
    )
    proposal = Fact.build(
        context=FACT_CONTEXT,
        kind="proposal",
        subject={"source_id": source.id, "anchor": unit.anchor},
        quote=quote,
        attributes=attributes,
        status=status,
        provenance={
            "source_id": source.id,
            "anchor": unit.anchor,
            "extractor": PROPOSER,
            "as_of": source.digest,
        },
        checks=[check_quote(quote, text, anchor=unit.anchor), check_proposal(attributes)],
    )
    return ApplicationOutcome(
        customer_id=applicant.customer_id,
        proposal=proposal,
        facts=[*facts, proposal],
        questions=questions,
        readings=readings,
        reasons=reasons,
    )
