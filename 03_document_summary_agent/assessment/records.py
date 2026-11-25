"""The records of a policy assessment: profile, register, candidates, judgements and the bundle.

Every record is strict and frozen. The engine writes them, the validators in
``assessment.validate`` check them, and the pages and the measures read them; none of the three
lanes changes a field here without the lead's ruling.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field

from fsi_common.records import Brief, CheckResult, Fact, Record
from fsi_common.records.base import Anchor, IsoDate, NonBlank, Part, SourceId, VersionTag

RegulationKey = Literal["DORA", "AI-ACT", "SS1-23"]
"""The keys of the regulations in ``data/regulations/sources.json``."""

State = Literal["covered", "partly covered", "not covered", "in conflict"]
"""What the documents in force state against a provision."""

STATES: tuple[State, ...] = ("covered", "partly covered", "not covered", "in conflict")

Addressee = Literal[
    "financial_entity",
    "management_body",
    "provider",
    "provider_high_risk",
    "provider_general_purpose",
    "deployer",
    "deployer_high_risk",
    "every_operator",
    "other_operator",
    "ict_third_party_provider",
    "authority",
    "commission",
    "member_state",
    "firm",
    "unclear",
]
"""Whom a provision binds, as the register's rule reads it from the provision's words."""

FoundBy = Literal["term", "defined_term", "cross_reference", "graph", "second_look"]
"""How code found a candidate clause for an obligation."""

Relation = Literal["implements", "refers_to", "supersedes", "defines", "delegates"]
"""The relations of the document graph."""

RELATIONS: tuple[Relation, ...] = ("implements", "refers_to", "supersedes", "defines", "delegates")

EVIDENCE_KINDS: tuple[str, ...] = ("provision", "clause")
"""The fact kinds that hold an assessment's two quotes, one per end."""

FACT_KINDS: frozenset[str] = frozenset(EVIDENCE_KINDS + RELATIONS)
"""The closed list of fact kinds this dataset declares to ``fsi_common``."""

COPIED_ATTRIBUTES: frozenset[str] = frozenset({"object_source_id", "object_anchor", "object_quote"})
"""The attributes copied word for word from a source: the far end of a graph fact."""


class ClauseRef(Part):
    """A numbered clause of a corpus document."""

    document: NonBlank = Field(description="The document's id in the corpus manifest")
    clause: NonBlank = Field(pattern=r"^\d+(\.\d+)+$", description="For example '4.1'")

    @property
    def anchor(self) -> str:
        """The clause's anchor, as a fact's subject names it."""
        return f"clause:{self.clause}"


class RoleBasis(Part):
    """One role an entity of the firm holds under one regulation, with the words it rests on."""

    regulation: RegulationKey
    role: Addressee = Field(description="The role the register's rule matches against")
    qualifier: str | None = Field(
        default=None, description="What narrows the role, for example 'high-risk' or 'Article 50'"
    )
    evidence: ClauseRef = Field(description="The clause of the firm's own documents that says so")
    quote: NonBlank = Field(description="The clause's words, word for word")


class AiSystem(Part):
    """An AI system the firm provides or deploys, with the features the AI Act's rules turn on."""

    name: NonBlank
    entity: NonBlank = Field(description="The legal entity that provides or deploys it")
    role: Literal["provider", "deployer"]
    high_risk: bool | None = Field(description="None when the documents do not settle it")
    interacts_with_natural_persons: bool | None
    generates_synthetic_content: bool | None
    evidence: ClauseRef
    quote: NonBlank


class FirmEntity(Part):
    """One legal entity of the firm."""

    name: NonBlank
    jurisdiction: Literal["UK", "EU"]
    microenterprise: bool | None = Field(
        description="Whether the entity is a microenterprise under DORA Article 3, point (60); "
        "None when the documents do not settle it"
    )
    microenterprise_basis: NonBlank = Field(description="What the answer rests on, in words")
    roles: list[RoleBasis]


class FirmProfile(Part):
    """The stated profile the register's applicability is decided from, by code."""

    corpus: NonBlank = Field(description="The corpus the profile describes")
    as_of: IsoDate = Field(description="The date applicability is judged at")
    entities: list[FirmEntity] = Field(min_length=1)
    ai_systems: list[AiSystem]


class Obligation(Part):
    """One unit of a regulation that the register's rule reads as binding someone."""

    obligation_id: NonBlank = Field(
        description="'<regulation> <anchor>', for example 'DORA art:5/2'"
    )
    regulation: RegulationKey
    anchor: Anchor = Field(description="The unit's anchor in the regulation reader")
    label: NonBlank = Field(description="How a reader cites it, for example 'Article 5(2)'")
    parents: list[str] = Field(
        description="The structure anchors the unit sits under, outermost first"
    )
    points: list[str] = Field(description="The unit's top-level point labels, bare, in order")
    provision_words: NonBlank = Field(description="The unit's text, word for word")
    binds: list[Addressee] = Field(min_length=1)
    binds_words: NonBlank = Field(description="The words of the unit that name whom it binds")
    applies_from: IsoDate | None
    applies_from_basis: NonBlank = Field(description="The provision that sets the date, in words")
    applies: bool | None = Field(description="None when the text leaves it to a person")
    applies_to: list[str] = Field(description="The entities it applies to; empty when it does not")
    reason: NonBlank = Field(description="Why it applies or not, in words")
    rule: VersionTag = Field(description="The register rule's name and version")


class UnitDisposition(Part):
    """What the register's rule made of one unit: an obligation, or not, with the reason."""

    regulation: RegulationKey
    anchor: Anchor
    outcome: Literal["obligation", "not an obligation"]
    reason: NonBlank


class Population(Part):
    """The register's counts for one regulation, each over the regulation's units."""

    regulation: RegulationKey
    units: int = Field(ge=0)
    obligations: int = Field(ge=0)
    not_obligations: int = Field(ge=0)
    applicable: int = Field(ge=0)
    not_applicable: int = Field(ge=0)
    undetermined: int = Field(ge=0)


class Register(Part):
    """Every unit of every regulation accounted for, and each obligation with its applicability."""

    corpus: NonBlank
    profile_digest: NonBlank = Field(description="sha256 of the profile's JSON")
    regulation_digests: dict[str, str] = Field(description="Each regulation's source digest")
    rule: VersionTag
    obligations: list[Obligation]
    dispositions: list[UnitDisposition]
    populations: list[Population]

    def population(self, regulation: str) -> Population:
        """Return the counts of one regulation.

        Args:
            regulation: A regulation key.

        Returns:
            Its population.

        Raises:
            KeyError: If the register holds no such regulation.
        """
        for population in self.populations:
            if population.regulation == regulation:
                return population
        raise KeyError(f"The register holds no regulation {regulation}.")

    def obligation(self, obligation_id: str) -> Obligation | None:
        """Return an obligation by id, or None.

        Args:
            obligation_id: For example ``DORA art:5/2``.

        Returns:
            The obligation, or None when the register has none by that id.
        """
        return next((o for o in self.obligations if o.obligation_id == obligation_id), None)


class Candidate(Part):
    """One clause code found for one obligation, kept or dropped, with why."""

    obligation_id: NonBlank
    clause: ClauseRef
    found_by: list[FoundBy] = Field(min_length=1)
    matched: list[str] = Field(min_length=1, description="The terms or references that matched")
    kept: bool
    reason: NonBlank


class CandidateText(Part):
    """A kept candidate as the judgement request carries it."""

    clause: ClauseRef
    document_title: NonBlank
    version: NonBlank
    in_force: bool
    heading: NonBlank
    text: NonBlank


class JudgementRequest(Part):
    """The inputs of the one model call for one applicable obligation."""

    obligation_id: NonBlank
    label: NonBlank
    provision_words: NonBlank
    points: list[str]
    applies_to: list[str]
    candidates: list[CandidateText]
    defined_terms: dict[str, str] = Field(description="Each defined term used, with its definition")
    prompt_version: VersionTag


class ClauseQuote(Part):
    """A clause quoted word for word."""

    clause: ClauseRef
    quote: NonBlank


class PointJudgement(Part):
    """The state of one top-level point of a provision, where the unit has points."""

    point: NonBlank
    state: State
    clause_quotes: list[ClauseQuote]
    gap: str | None


class JudgementAnswer(Part):
    """What the model answers for one obligation; plain code checks it before it is used."""

    obligation_id: NonBlank
    state: State
    provision_quote: NonBlank
    clause_quotes: list[ClauseQuote]
    gap: str | None = Field(description="The gap in words; required unless covered")
    suggested_wording: str | None
    points: list[PointJudgement]
    reason: NonBlank


class Judgement(Part):
    """One model call: its role, model, request and answer, keyed for record and replay."""

    role: Literal["assess"]
    model: NonBlank
    request_digest: NonBlank = Field(description="sha256 of the request's JSON, the replay key")
    request: JudgementRequest
    answer: JudgementAnswer


class Assessment(Record):
    """One applicable obligation assessed against the documents in force.

    ``assessed_by`` is ``model`` when a judgement stands behind it, and ``code`` only for an
    obligation that had no candidate on either look and so is not covered without a call.
    """

    SCHEMA: ClassVar[str] = "policy_assessment.v1"
    ID_PREFIX: ClassVar[str] = "assessment"

    schema_id: Literal["policy_assessment.v1"] = Field(
        default="policy_assessment.v1", alias="schema"
    )
    id: NonBlank
    obligation_id: NonBlank
    regulation: RegulationKey
    state: State
    provision_quote: NonBlank
    clause_quotes: list[ClauseQuote]
    gap: str | None
    suggested_wording: str | None
    points: list[PointJudgement]
    second_look: bool = Field(description="Whether the second look ran")
    assessed_by: Literal["model", "code"]
    evidence: list[str] = Field(min_length=1, description="Ids of the provision and clause facts")
    checks: list[CheckResult] = Field(min_length=1)


class ClauseMapping(Part):
    """One clause in force: the obligations it was mapped to, or why it maps to none."""

    clause: ClauseRef
    obligations: list[str]
    unmapped_reason: str | None


class SeedMatch(Part):
    """How one seed was matched to the assessments, and the state found there."""

    seed_id: NonBlank
    regulation: RegulationKey
    target: NonBlank = Field(description="The anchor or structure node the seed resolves to")
    points: list[str]
    obligation_ids: list[str] = Field(min_length=1)
    found_state: State
    seeded_state: State
    cited_clauses: list[ClauseRef]
    seeded_clauses: list[ClauseRef]


class NotIncluded(Part):
    """A regulation a run left out, with why and the commands that bring it in."""

    regulation: RegulationKey
    reason: NonBlank
    commands: list[NonBlank] = Field(min_length=1)


class BundleIndex(Part):
    """The bundle's own record: what it is, what it was built from and what it counts."""

    schema_id: Literal["policy_assessment_bundle.v1"] = Field(
        default="policy_assessment_bundle.v1", alias="schema"
    )
    corpus: NonBlank
    run: Literal["fake", "record", "replay"]
    scope: list[str] = Field(
        description="The obligation ids the run assessed; empty means every applicable one. Only "
        "a fake run may narrow it."
    )
    instructions_digest: str | None = Field(
        default=None,
        description="sha256 of the judge's instructions file the run used; None for a fake run "
        "or a bundle made before the field existed",
    )
    not_included: list[NotIncluded] = Field(
        default_factory=list,
        description="Regulations the run left out, each with its reason and the commands that "
        "fetch its text and record its calls",
    )
    source_ids: list[SourceId] = Field(min_length=1)
    counts: dict[str, int]


class Bundle(Part):
    """Everything the pages and the measures read, held in memory."""

    index: BundleIndex
    obligation_register: Register
    candidates: list[Candidate]
    judgements: list[Judgement]
    assessments: list[Assessment]
    facts: list[Fact]
    clause_map: list[ClauseMapping]
    seed_matches: list[SeedMatch]
    gap_report: Brief
