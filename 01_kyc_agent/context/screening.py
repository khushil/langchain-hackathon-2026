"""One application against one list entry, by the starter's own measure of two names.

The starter's rule is a name score of 0.85 or more. This layer keeps that measure and that
threshold and adds one thing: a floor, 0.60, below which two names share too little to ask about.
A pair under the floor ends on the list of screenings with no likeness, with its score as the
reason. On the starter's data the 350 name pairs leave a gap: 15 score 0.909 or more, three lie
between the floor and the threshold (0.615, 0.615 and 0.640) and the highest pair under the floor
scores 0.593, so the floor has 0.007 under it and 0.015 above it; a floor of 0.65 would lose the
three pairs between 0.60 and 0.65, the 0.640 among them, and tests hold these figures to the data.

A pair at or over the floor is a fact. It ends settled by the checks only on an exact name and an
agreeing date of birth against a sanctions entry; every other pair is kept with the check that
did not settle it and put to a person with both readings side by side.
"""

from __future__ import annotations

from dataclasses import dataclass

from context.checks import (
    check_dob_comparison,
    check_quote,
    check_score,
)
from context.extraction import Applicant
from context.reader import ListEntry
from context.readings import Readings
from context.text import contains_word_for_word
from fsi_common.records import Extractor, Fact, OpenQuestion, Source, SourceUnit
from tools.screening import MATCH_THRESHOLD, name_similarity
from utils.records import FACT_CONTEXT

NEAR_FLOOR = 0.60
"""Below this score two names have no likeness worth asking about; ours, beside the starter's."""

SCREENER = Extractor(name="name-screening", version="0.1.0")
"""The step that sets one application against one list entry; code, so its facts name no model."""

ASK_ROLE = "Head of Compliance"
LIST_LABELS = {"sanctions": "sanctions list", "pep": "PEP list"}
SAME, DIFFERENT = "The same person", "A different person"


@dataclass(frozen=True)
class PairResult:
    """What became of one screening: a fact and maybe a question, or a reason it has no fact."""

    anchor: str
    entry: ListEntry
    fact: Fact | None = None
    question: OpenQuestion | None = None
    readings: Readings | None = None
    reason: str | None = None
    settles: bool = False
    not_run: bool = False
    score: float | None = None


def _score(value: float) -> str:
    return f"{round(value, 2):.2f}"


def _surname(name: str) -> str:
    return name.split()[-1].lower() if name.split() else ""


def _readings(
    *,
    applicant_name: str,
    applicant_dob: str | None,
    entry: ListEntry,
    score: float,
    dob_agrees: bool | None,
    text: str,
    subject: str,
) -> tuple[list[str], list[str]]:
    same: list[str] = []
    different: list[str] = []
    if score >= 1.0:
        same.append(f"The names are identical, {entry.name}.")
    else:
        side = "over" if score >= MATCH_THRESHOLD else "under"
        same.append(
            f"The names score {_score(score)} by the starter's measure, {side} its threshold "
            f"of {MATCH_THRESHOLD:.2f}."
        )
        different.append(f'The names are not identical: "{subject}" and "{entry.name}".')
    if _surname(subject) == _surname(entry.name) and score < 1.0:
        same.append(f'The surname "{entry.name.split()[-1]}" is shared.')
    if dob_agrees is True:
        same.append(f"The dates of birth agree, {entry.date_of_birth}.")
    elif dob_agrees is False:
        different.append(
            f"The dates of birth differ: {applicant_dob} on the application, "
            f"{entry.date_of_birth} on the list."
        )
    elif entry.date_of_birth is not None:
        different.append(
            "The applicant's date of birth was not established, so it cannot support the match."
        )
    if entry.list == "pep":
        position, _, country = entry.detail.rpartition(", ")
        has_post = contains_word_for_word(position, text)
        has_country = contains_word_for_word(country, text)
        if has_post:
            same.append(f'The application states the post "{position}" the entry gives.')
        if has_country:
            same.append(f'The application names the country "{country}" the entry gives.')
        if not has_post and not has_country:
            different.append(
                f'The application mentions neither the post "{position}" nor the country '
                f'"{country}" the entry gives.'
            )
    return same, different or [
        "A match on the name alone is not confirmed by anything else the application states."
    ]


def _why_unsettled(
    score: float, dob_agrees: bool | None, entry: ListEntry, about: str, applicant_dob: str | None
) -> str:
    parts = []
    if about == "relation":
        parts.append("The likeness is with the applicant's relation, not with the applicant.")
    if score < 1.0:
        parts.append(f"The names are not identical (score {_score(score)}).")
    if dob_agrees is False:
        parts.append("The dates of birth differ.")
    if entry.date_of_birth is None:
        parts.append(
            f"The {LIST_LABELS[entry.list]} has no date of birth, so the match cannot be "
            "confirmed or ruled out on it."
        )
    elif applicant_dob is None:
        parts.append("The applicant's date of birth was not established.")
    return " ".join(parts) or "The checks do not settle it."


def screen_pair(
    applicant: Applicant, entry: ListEntry, *, source: Source, unit: SourceUnit, unit_text: str
) -> PairResult:
    """Set one application against one list entry.

    Args:
        applicant: What the reading of the application gives, each detail only if it passed.
        entry: The list entry.
        source: The screenings source.
        unit: The unit of this pair.
        unit_text: The unit's text: the application and the entry's line.

    Returns:
        A pair with no likeness (a reason, its score in it), one not run because the name did
        not pass its check (a reason saying so), or a screening fact with its checks, settled or
        with a question and both readings.
    """
    if applicant.name is None:
        return PairResult(
            anchor=unit.anchor,
            entry=entry,
            not_run=True,
            reason=(
                "Not screened: the applicant's name did not pass its check, so this application "
                f"was not set against {entry.name}."
            ),
        )
    own = name_similarity(applicant.name, entry.name)
    related = applicant.relation.related_name if applicant.relation else None
    relative = name_similarity(related, entry.name) if related else None
    strongest = max(own, relative or 0.0)
    if strongest < NEAR_FLOOR:
        shown = f"the names score {_score(own)}"
        if relative is not None:
            shown += f" and the relation's name scores {_score(relative)}"
        return PairResult(
            anchor=unit.anchor,
            entry=entry,
            score=strongest,
            reason=(
                f"No likeness: {shown} against {entry.name} on the {LIST_LABELS[entry.list]}, "
                f"below the floor of {NEAR_FLOOR:.2f}."
            ),
        )
    about = "applicant" if own >= NEAR_FLOOR else "relation"
    score = own if about == "applicant" else strongest
    subject = applicant.name if about == "applicant" else related
    dob_agrees = (
        None
        if about == "relation" or applicant.date_of_birth is None or entry.date_of_birth is None
        else applicant.date_of_birth == entry.date_of_birth
    )
    settles = (
        entry.list == "sanctions" and about == "applicant" and own >= 1.0 and dob_agrees is True
    )
    text = unit_text.split("\n", 1)[0]
    same, different = _readings(
        applicant_name=applicant.name,
        applicant_dob=applicant.date_of_birth,
        entry=entry,
        score=score,
        dob_agrees=dob_agrees,
        text=text,
        subject=subject,
    )
    why = (
        None
        if settles
        else _why_unsettled(score, dob_agrees, entry, about, applicant.date_of_birth)
    )
    settled_by = (
        f"Exact name and date of birth match with {entry.name} on the sanctions list "
        f"({entry.detail})."
        if settles
        else None
    )
    attributes = {
        "list": entry.list,
        "about": about,
        "entry_name": entry.name,
        "entry_detail": entry.detail,
        "entry_dob": entry.date_of_birth,
        "applicant_name": applicant.name,
        "applicant_dob": applicant.date_of_birth,
        "name_score": _score(own),
        "relation_name": related,
        "relation_score": None if relative is None else _score(relative),
        "dob_agrees": dob_agrees,
        "strength": "match" if strongest >= MATCH_THRESHOLD else "near",
        "outcome": "settled" if settles else "unsettled",
        "settled_by": settled_by,
        "why_unsettled": why,
        "reading_same": same,
        "reading_different": different,
    }
    fact = Fact.build(
        context=FACT_CONTEXT,
        kind="screening",
        subject={"source_id": source.id, "anchor": unit.anchor},
        quote=entry.name,
        attributes=attributes,
        status={"status": "documented"},
        provenance={
            "source_id": source.id,
            "anchor": unit.anchor,
            "extractor": SCREENER,
            "as_of": source.digest,
        },
        checks=[
            check_quote(entry.name, unit_text, anchor=unit.anchor),
            check_score(applicant.name, entry.name, attributes["name_score"]),
            check_dob_comparison(applicant.date_of_birth, entry.date_of_birth, dob_agrees)
            if about == "applicant"
            else check_dob_comparison(None, entry.date_of_birth, None),
        ],
    )
    if settles:
        return PairResult(anchor=unit.anchor, entry=entry, fact=fact, settles=True, score=strongest)
    readings = Readings(same_label=SAME, same=same, different_label=DIFFERENT, different=different)
    who = (
        applicant.name
        if about == "applicant"
        else f"the applicant's {applicant.relation.relation} {related}"
    )
    question = OpenQuestion.build(
        about={"source_id": source.id, "anchor": unit.anchor},
        question=(
            f"Is {who} ({applicant.customer_id}) the same person as {entry.name} on the "
            f"{LIST_LABELS[entry.list]} ({entry.detail}), or a different person?"
        ),
        why_unknown=f"The name check found a likeness it cannot settle. {why}",
        impact=(
            "If the same person, this entry puts the application at high risk; if a different "
            "person, it does not raise the risk."
        ),
        ask_role=ASK_ROLE,
        reason="ambiguous_meaning",
        cites=[
            i for i in (fact.id, applicant.name_fact_id, applicant.date_fact_id) if i is not None
        ],
        priority=(
            "low"
            if fact.attributes["strength"] == "near"
            else "high"
            if entry.list == "sanctions"
            else "medium"
        ),
        state="open",
    )
    return PairResult(
        anchor=unit.anchor,
        entry=entry,
        fact=fact,
        question=question,
        readings=readings,
        score=strongest,
    )
