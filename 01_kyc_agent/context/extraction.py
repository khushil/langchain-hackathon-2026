"""One application's reading, as the model returns it, becomes cited facts and open questions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from pydantic import BaseModel, Field

from context.checks import (
    check_amount,
    check_date,
    check_name,
    check_quote,
    check_words,
)
from context.errors import ApplicantReadError
from fsi_common.records import CheckResult, Extractor, Fact, OpenQuestion, Source, SourceUnit
from utils.records import FACT_CONTEXT

READER = Extractor(name="applicant-reader", version="0.1.0")
"""The step that reads one application into the applicant's details, with a model."""

ASK_ROLE = "Head of Compliance"


class Detail(BaseModel):
    """One detail the application states, with the words it states it in."""

    value: str = Field(description="The detail, in the form the field asks for")
    quote: str = Field(
        description="The words of the application that state it, copied word for word, "
        "at most 30 words"
    )


class RelationRead(BaseModel):
    """A relation the applicant names to another person."""

    relation: str = Field(description="The relation in one word, for example 'husband'")
    quote: str = Field(
        description="The words of the application that state it, copied word for word"
    )
    related_name: str | None = Field(
        description="The other person's name as written, or null if none is given"
    )
    related_office: str | None = Field(
        description="The public office or post the application says the other person holds, "
        "as written, or null if none is given"
    )


class ApplicantRead(BaseModel):
    """What the model reads from one application."""

    full_name: Detail = Field(description="The applicant's full name; the value is as written")
    date_of_birth: Detail = Field(
        description="The date of birth; the value is YYYY-MM-DD, the quote the date as written"
    )
    nationality: Detail = Field(description="The country of citizenship")
    occupation: Detail = Field(description="The job title or role")
    source_of_funds: Detail = Field(description="Where the money to be deposited comes from")
    funds_amount: Detail = Field(
        description="The amount to be deposited; the value is the amount as written, "
        "for example '$5,000 a month'"
    )
    relation: RelationRead | None = Field(
        default=None,
        description="A relation the applicant names to another person, or null if none is named",
    )


@dataclass(frozen=True)
class Relation:
    """A relation as a passing fact states it."""

    fact_id: str
    relation: str
    related_name: str | None
    related_office: str | None

    def to_json(self) -> dict[str, str | None]:
        """Return the relation as JSON, for the graph's state."""
        return asdict(self)


@dataclass(frozen=True)
class Applicant:
    """What the screening may rely on: each detail only when its fact passed every check."""

    customer_id: str
    name: str | None
    name_fact_id: str | None
    date_of_birth: str | None
    date_fact_id: str | None
    relation: Relation | None = None

    def to_json(self) -> dict:
        """Return the applicant as JSON, for the graph's state."""
        return {
            **{k: v for k, v in asdict(self).items() if k != "relation"},
            "relation": None if self.relation is None else self.relation.to_json(),
        }

    @classmethod
    def from_json(cls, data: dict) -> Applicant:
        """Return the applicant a state holds.

        Args:
            data: What ``to_json`` returned.

        Returns:
            The applicant.
        """
        relation = data.get("relation")
        return cls(**{**data, "relation": None if relation is None else Relation(**relation)})


@dataclass(frozen=True)
class ApplicantFacts:
    """One application read: its facts, its questions and what a screening may rely on."""

    applicant: Applicant
    facts: list[Fact] = field(default_factory=list)
    questions: list[OpenQuestion] = field(default_factory=list)


def _value(fact: Fact | None) -> str | None:
    return None if fact is None else fact.attributes["value"]


def _id(fact: Fact | None) -> str | None:
    return None if fact is None else fact.id


def _stripped(text: str | None) -> str | None:
    return None if text is None or not text.strip() else text.strip()


def _blank(text: str | None) -> bool:
    return text is None or not text.strip()


def _fact(
    kind: str,
    *,
    source: Source,
    unit: SourceUnit,
    quote: str,
    attributes: dict,
    checks: list[CheckResult],
    model: str,
    prompt_version: str,
) -> Fact:
    return Fact.build(
        context=FACT_CONTEXT,
        kind=kind,
        subject={"source_id": source.id, "anchor": unit.anchor},
        quote=quote.strip(),
        attributes=attributes,
        status={"status": "documented"},
        provenance={
            "source_id": source.id,
            "anchor": unit.anchor,
            "extractor": READER,
            "model": model,
            "prompt_version": prompt_version,
            "as_of": source.digest,
        },
        checks=checks,
    )


def _missing_question(
    what: str, *, source: Source, unit: SourceUnit, customer_id: str, cites: list[str]
) -> OpenQuestion:
    return OpenQuestion.build(
        about={"source_id": source.id, "anchor": unit.anchor},
        question=f"What is the applicant's {what} in the application {customer_id}?",
        why_unknown=(
            f"The reader gave no {what} with words of the application behind it, or gave one "
            "the application does not write, so no screening that depends on it could be run."
        ),
        impact=(
            "Until it is known the application cannot be screened, so it cannot be settled by "
            "the checks and a person decides it."
        ),
        ask_role=ASK_ROLE,
        reason="missing_data",
        cites=cites or [unit.id],
        priority="high",
        state="open",
    )


def read_applicant(
    reading: ApplicantRead,
    *,
    source: Source,
    unit: SourceUnit,
    text: str,
    model: str,
    prompt_version: str,
) -> ApplicantFacts:
    """Turn one reading of one application into checked facts and open questions.

    Each detail the reader gave with a quote becomes a fact with its checks: the quote is word for
    word in the application, the name is written there, the date reads as its words, the amount is
    written there. A fact that fails a check stays on the record with the failed check, and what
    the screening may rely on leaves it out. A detail given with no quote is no fact; it is asked
    about, never dropped. A name that is not established is asked about too.

    Args:
        reading: The reader's result, as the model returned it.
        source: The applications source.
        unit: The application's unit.
        text: The application's text.
        model: The model that produced the reading.
        prompt_version: The version of the prompt it was asked with.

    Returns:
        The facts, the questions and what the screening may rely on.

    Raises:
        ApplicantReadError: If the application's text is empty.
    """
    customer_id = unit.anchor.partition(":")[2]
    if _blank(text):
        raise ApplicantReadError(f"The application {customer_id} has no text to read.")
    anchor = unit.anchor
    common = {"source": source, "unit": unit, "model": model, "prompt_version": prompt_version}
    facts: list[Fact] = []
    questions: list[OpenQuestion] = []
    passed: dict[str, Fact] = {}

    def add(kind: str, label: str, detail: Detail, attributes: dict, extra: list[CheckResult]):
        if _blank(detail.quote) or _blank(detail.value):
            questions.append(
                _missing_question(
                    label, source=source, unit=unit, customer_id=customer_id, cites=[]
                )
            )
            return None
        fact = _fact(
            kind,
            quote=detail.quote,
            attributes=attributes,
            checks=[check_quote(detail.quote, text, anchor=anchor), *extra],
            **common,
        )
        facts.append(fact)
        if fact.passed_checks:
            passed[kind] = fact
        return fact

    name = reading.full_name
    name_fact = add(
        "applicant_name",
        "name",
        name,
        {"value": name.value.strip()},
        [check_name(name.value, text, anchor=anchor)],
    )
    dob = reading.date_of_birth
    add(
        "birth_date",
        "date of birth",
        dob,
        {"value": dob.value.strip()},
        [check_date(dob.quote, dob.value.strip(), anchor=anchor)],
    )
    for kind, label, detail in (
        ("nationality", "nationality", reading.nationality),
        ("occupation", "occupation", reading.occupation),
        ("source_of_funds", "source of funds", reading.source_of_funds),
    ):
        add(kind, label, detail, {"value": detail.value.strip()}, [])
    amount = reading.funds_amount
    add(
        "funds_amount",
        "amount of funds",
        amount,
        {"amount": amount.value.strip()},
        [check_amount(amount.value, text, anchor=anchor)],
    )
    relation = _read_relation(reading.relation, text, unit, common, facts, passed, questions)
    if "applicant_name" not in passed:
        cites = [name_fact.id] if name_fact is not None else []
        if not any("name" in q.question for q in questions):
            questions.append(
                _missing_question(
                    "name", source=source, unit=unit, customer_id=customer_id, cites=cites
                )
            )
    return ApplicantFacts(
        applicant=Applicant(
            customer_id=customer_id,
            name=passed["applicant_name"].attributes["value"]
            if "applicant_name" in passed
            else None,
            name_fact_id=passed["applicant_name"].id if "applicant_name" in passed else None,
            date_of_birth=passed["birth_date"].attributes["value"]
            if "birth_date" in passed
            else None,
            date_fact_id=passed["birth_date"].id if "birth_date" in passed else None,
            relation=relation,
        ),
        facts=facts,
        questions=questions,
    )


def _failed_relation_question(
    relation: str, cites: list[str], source: Source, unit: SourceUnit
) -> OpenQuestion:
    """Ask about a relation whose words are missing or not in the application."""
    customer_id = unit.anchor.partition(":")[2]
    return OpenQuestion.build(
        about={"source_id": source.id, "anchor": unit.anchor},
        question=(
            f"The reader found a relation, the {relation}, whose words do not appear in the "
            f"application {customer_id}. Who is the {relation}, and does that person hold "
            "public office?"
        ),
        why_unknown=(
            "The words the reader gave for the relation, its name or its office are not written "
            "in the application, so no screening of the relation could rely on them."
        ),
        impact=(
            "Until it is known whether the relation holds public office the application cannot "
            "be settled by the checks, and a person decides it."
        ),
        ask_role=ASK_ROLE,
        reason="missing_data",
        cites=cites or [unit.id],
        priority="medium",
        state="open",
    )


def _read_relation(
    relation: RelationRead | None,
    text: str,
    unit: SourceUnit,
    common: dict,
    facts: list[Fact],
    passed: dict[str, Fact],
    questions: list[OpenQuestion],
) -> Relation | None:
    if relation is None:
        return None
    if _blank(relation.quote) or _blank(relation.relation):
        said = any(
            not _blank(given)
            for given in (
                relation.relation,
                relation.quote,
                relation.related_name,
                relation.related_office,
            )
        )
        if said:
            word = _stripped(relation.relation) or "relation"
            questions.append(_failed_relation_question(word, [], common["source"], unit))
        return None
    anchor = unit.anchor
    checks = [check_quote(relation.quote, text, anchor=anchor)]
    for label, given in (
        ("name", relation.related_name),
        ("office", relation.related_office),
    ):
        if not _blank(given):
            checks.append(check_words(given, f"relation's {label}", text, anchor=anchor))
    fact = _fact(
        "relation",
        quote=relation.quote,
        attributes={
            "relation": relation.relation.strip(),
            "related_name": None
            if _blank(relation.related_name)
            else relation.related_name.strip(),
            "related_office": _stripped(relation.related_office),
        },
        checks=checks,
        **common,
    )
    facts.append(fact)
    if not fact.passed_checks:
        questions.append(
            _failed_relation_question(
                fact.attributes["relation"], [fact.id], common["source"], unit
            )
        )
        return None
    passed["relation"] = fact
    return Relation(
        fact_id=fact.id,
        relation=fact.attributes["relation"],
        related_name=fact.attributes["related_name"],
        related_office=fact.attributes["related_office"],
    )
