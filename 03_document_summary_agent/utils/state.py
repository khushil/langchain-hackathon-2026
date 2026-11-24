"""The compliance brief graph's state, its review interrupt, and the store namespaces for decisions.

State values are records as JSON (``record.to_json()``), validated with ``fsi_common`` at each
node's boundary, because LangGraph's checkpointer stores JSON safely and refuses unregistered
Python types in a future version. Collections are dicts keyed by id, merged by reducers that sort
their keys, so parallel section writers give the same state in any order of completion. Facts
are the one collection where an id may arrive with two contents (a fact's id leaves out what a
model words), so each fact id holds a list with one content per judged digest, side by side.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Annotated, Any, TypedDict

from pydantic import Field, model_validator

from fsi_common.ids import digest_json
from fsi_common.records import (
    CarryOver,
    Decision,
    Disagreement,
    Extractor,
    Fact,
    OpenQuestion,
    Person,
    SignOff,
    carry_over,
    fact_judged_basis,
    judged_differences,
    judged_digest,
    record_digest,
)
from fsi_common.records.base import BriefId, Digest, NonBlank, Part, StatementId
from utils.records import FACT_CONTEXT

RecordJson = dict[str, Any]
"""A record as JSON, as ``fsi_common`` writes it."""

STORE_ROOT = "compliance-brief"


class ConflictingWriteError(Exception):
    """Two writers gave different content under one key, which content-derived ids rule out."""


class InvalidFactWriteError(ValueError):
    """A node wrote facts in another shape than ``{fact id: [fact JSON, ...]}``."""


class ReviewMismatchError(ValueError):
    """A review response does not answer the request the reviewer was shown."""


class InvalidNamespaceLabelError(ValueError):
    """A store namespace label is empty or holds a full stop, which LangGraph's store refuses."""


def _section_order(key: str) -> tuple[int | str, ...]:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"[.]", key))


def merge_records(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Merge two writes of records keyed by id; the same id must carry the same content.

    Args:
        left: The state's records so far.
        right: A node's new records.

    Returns:
        Every record, keys sorted.

    Raises:
        ConflictingWriteError: If one id arrives with two different contents.
    """
    merged = dict(left or {})
    for key, value in (right or {}).items():
        if key in merged and merged[key] != value:
            raise ConflictingWriteError(f"Two different records were written under {key}.")
        merged[key] = value
    return dict(sorted(merged.items()))


def merge_fact_variants(
    left: dict[str, list[RecordJson]] | None, right: dict[str, list[RecordJson]] | None
) -> dict[str, list[RecordJson]]:
    """Merge writes of facts, keeping every judged content under one id side by side.

    A fact's id leaves out what a model words, so two section readers, or a reader and a rerun,
    can write one id with two contents. Contents that differ in what a person judges are both
    kept and nothing raises; ``variant_disagreements`` turns them into a disagreement the engine
    records. Contents that differ only outside it (the provenance, a check's wording) are one
    fact for the reviewer, and exactly one copy is kept: the one with the lowest record digest,
    whichever write arrived first.

    Args:
        left: The state's facts so far, each id holding its list of contents.
        right: A node's new facts in the same shape; ``fact_writes`` builds it.

    Returns:
        Every fact id, sorted, each with one content per judged digest, in judged digest order.

    Raises:
        InvalidFactWriteError: If a write holds a fact id whose value is not a list of fact JSON.
    """
    merged: dict[str, dict[str, RecordJson]] = {}
    for side in (left or {}, right or {}):
        for key, contents in side.items():
            if not isinstance(contents, list) or not all(isinstance(c, dict) for c in contents):
                raise InvalidFactWriteError(
                    f"Facts under {key} were written as {type(contents).__name__}; write "
                    "{fact id: [fact JSON, ...]}, as fact_writes builds it."
                )
            by_judged = merged.setdefault(key, {})
            for content in contents:
                try:
                    judged = digest_json(fact_judged_basis(content))
                except (KeyError, TypeError) as exc:
                    raise InvalidFactWriteError(
                        f"A content written under {key} is not fact JSON ({exc!r})."
                    ) from exc
                kept = by_judged.get(judged)
                if kept is None or digest_json(content) < digest_json(kept):
                    by_judged[judged] = content
    return {
        key: [by_judged[judged] for judged in sorted(by_judged)]
        for key, by_judged in sorted(merged.items())
    }


def fact_writes(facts: Iterable[Fact]) -> dict[str, list[RecordJson]]:
    """Return facts in the shape a node writes to the state's ``facts``.

    Args:
        facts: The facts a node produced.

    Returns:
        ``{fact id: [fact JSON, ...]}``.
    """
    return merge_fact_variants(None, {fact.id: [fact.to_json()] for fact in facts})


def fact_variants(facts: dict[str, list[RecordJson]]) -> dict[str, list[RecordJson]]:
    """Return the fact ids that hold more than one content.

    Args:
        facts: The state's facts.

    Returns:
        Each such id with its contents; empty when every id holds one.
    """
    return {key: contents for key, contents in facts.items() if len(contents) > 1}


def variant_disagreements(
    facts: dict[str, list[RecordJson]], *, found_by: Extractor
) -> list[Disagreement]:
    """Return one open disagreement for each fact id that holds two or more judged contents.

    The reducer already keeps one copy of contents that differ only outside the judged fields,
    so every id with two or more contents here is a disagreement about what a person judges.

    Args:
        facts: The state's facts.
        found_by: The step that compared them, named and versioned.

    Returns:
        The disagreements, in fact id order, each naming every content by id and judged digest.
    """
    found = []
    for key, contents in fact_variants(facts).items():
        variants = [Fact.model_validate(c, context=FACT_CONTEXT) for c in contents]
        judged = {judged_digest(f): f for f in variants}
        if len(judged) < 2:
            continue
        first, *others = [judged[d] for d in sorted(judged)]
        changed = sorted(
            {n for f in others for n in judged_differences(first.judged_basis(), f.judged_basis())}
        )
        found.append(
            Disagreement.build(
                about=f"Readings of {first.subject.anchor} differ under one fact in: "
                + ", ".join(changed),
                claims=[{"fact_id": key, "judged_digest": d} for d in sorted(judged)],
                found_by=found_by,
                status="open",
            )
        )
    return found


def update_records(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Merge two writes of records whose state may move on, such as an open question being answered.

    Args:
        left: The state's records so far.
        right: A node's new or updated records; an update replaces the earlier copy.

    Returns:
        Every record, keys sorted.
    """
    return dict(sorted({**(left or {}), **(right or {})}.items()))


def merge_sections(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Merge per-section results written in parallel, one writer per section.

    Args:
        left: The results so far, by section number.
        right: One or more sections' new results.

    Returns:
        Every result, in section order (2 before 10).

    Raises:
        ConflictingWriteError: If one section arrives with two different results.
    """
    merged = merge_records(left, right)
    return dict(sorted(merged.items(), key=lambda item: _section_order(item[0])))


class BriefRequest(TypedDict):
    """What the user asked for."""

    document_id: str
    firm_id: str
    request: str


class BriefInput(TypedDict):
    """The graph's input."""

    request: BriefRequest


class RunCheck(TypedDict):
    """The result of one plain-code check on the run, such as the paragraph accounting closing."""

    check: str
    subject_id: str
    outcome: str
    detail: str


class BriefState(BriefInput, total=False):
    """The shared state of one run, from the request to the sign-off."""

    sources: Annotated[dict[str, RecordJson], merge_records]
    """``source.v1`` records by id: the document and the firm's tables."""
    units: Annotated[dict[str, RecordJson], merge_records]
    """``source_unit.v1`` records by id: every paragraph and table row read."""
    unit_text: Annotated[dict[str, str], merge_records]
    """Each unit's text by unit id, as split; the digest in the unit record is of this text."""
    section_results: Annotated[dict[str, RecordJson], merge_sections]
    """``SectionResult`` JSON by section number, one writer per section."""
    facts: Annotated[dict[str, list[RecordJson]], merge_fact_variants]
    """``fact.v1`` records by id, each id holding one content per judged digest; an id with two
    or more is recorded as a disagreement (``variant_disagreements``)."""
    check_results: Annotated[dict[str, RunCheck], merge_records]
    """Run-level checks by ``<check>|<subject id>``."""
    accounting: Annotated[dict[str, RecordJson], merge_records]
    """``unit_accounting.v1`` records by source id."""
    open_questions: Annotated[dict[str, RecordJson], update_records]
    """``open_question.v1`` records by id; a decision moves a question's state."""
    disagreements: Annotated[dict[str, RecordJson], update_records]
    """``disagreement.v1`` records by id."""
    draft_brief: RecordJson | None
    """The ``brief.v1`` record put to the reviewer."""
    decisions: Annotated[dict[str, RecordJson], merge_records]
    """``decision.v1`` records by id, this run's and earlier runs' from the store."""
    sign_off: RecordJson | None
    """The ``signoff.v1`` record, once the reviewer has signed or returned the brief."""


class CitedFact(Part):
    """One fact as the reviewer sees it, beside its source paragraph and any earlier decision.

    ``carry`` says what became of the latest earlier decision on the fact's id: carried (shown as
    decided, with its date and reviewer), ask again (shown with the earlier decision and what
    changed), or fresh. It must be what ``carry_over`` gives for that decision and this fact.
    """

    fact: Fact = Field(description="The fact")
    seen_digest: Digest = Field(description="The digest a decision on this fact must carry")
    unit_text: NonBlank = Field(description="The full text of the unit the fact quotes")
    carry: CarryOver = Field(description="What becomes of the earlier decision on this fact")

    @model_validator(mode="after")
    def _digest_is_the_facts(self) -> CitedFact:
        if self.seen_digest != record_digest(self.fact):
            raise ValueError(f"seen_digest is not the digest of fact {self.fact.id}")
        if self.carry != carry_over(self.carry.decision, self.fact):
            raise ValueError(f"carry is not what carry_over gives for fact {self.fact.id}")
        return self


class ReviewStatement(Part):
    """One statement of the brief with every fact it cites."""

    statement_id: StatementId
    heading: NonBlank | None = None
    text: NonBlank
    facts: list[CitedFact] = Field(min_length=1)


class ReviewRequest(Part):
    """The review interrupt's payload: the brief as the reviewer will read and sign it."""

    brief_id: BriefId
    brief_digest: Digest
    request: NonBlank
    statements: list[ReviewStatement] = Field(min_length=1)
    open_questions: list[OpenQuestion]

    def to_payload(self) -> dict[str, Any]:
        """Return the payload as JSON for ``interrupt()``.

        Returns:
            The request as a dict of JSON values.
        """
        return self.model_dump(mode="json", by_alias=True)


class ReviewResponse(Part):
    """The value the review interrupt resumes with: the reviewer and what they decided."""

    reviewer: Person
    decisions: list[Decision]
    sign_off: SignOff | None = None

    @model_validator(mode="after")
    def _one_reviewer(self) -> ReviewResponse:
        people = {(d.reviewer.name, d.reviewer.role) for d in self.decisions}
        if self.sign_off is not None:
            people.add((self.sign_off.reviewer.name, self.sign_off.reviewer.role))
        if people - {(self.reviewer.name, self.reviewer.role)}:
            raise ValueError("every decision and the sign-off are the reviewer's own")
        return self

    def check_against(self, request: ReviewRequest) -> None:
        """Confirm the response answers this request: its sign-off is for this brief at this digest.

        Args:
            request: The payload the reviewer was shown.

        Raises:
            ReviewMismatchError: If the sign-off names another brief or another digest.
        """
        if self.sign_off is not None and (self.sign_off.brief_id, self.sign_off.brief_digest) != (
            request.brief_id,
            request.brief_digest,
        ):
            raise ReviewMismatchError(
                "the sign-off is not for the brief and digest the reviewer was shown"
            )


def _labels(*labels: str) -> tuple[str, ...]:
    for label in labels:
        if not label or "." in label:
            raise InvalidNamespaceLabelError(f"'{label}' cannot be a store namespace label")
    return labels


def decisions_namespace(firm_id: str, document_id: str) -> tuple[str, ...]:
    """Return the store namespace of a firm's decisions on a document, read again on a rerun.

    Args:
        firm_id: The firm, for example ``FIRM-001``.
        document_id: The document's own key, for example ``PS26-4``.

    Returns:
        ``("compliance-brief", "decisions", firm_id, document_id)``; items are keyed by decision id.

    Raises:
        InvalidNamespaceLabelError: If a label is empty or holds a full stop.
    """
    return _labels(STORE_ROOT, "decisions", firm_id, document_id)


def sign_offs_namespace(firm_id: str, document_id: str) -> tuple[str, ...]:
    """Return the store namespace of a firm's sign-offs of briefs on a document.

    Args:
        firm_id: The firm.
        document_id: The document's own key.

    Returns:
        ``("compliance-brief", "sign-offs", firm_id, document_id)``; items are keyed by sign-off id.

    Raises:
        InvalidNamespaceLabelError: If a label is empty or holds a full stop.
    """
    return _labels(STORE_ROOT, "sign-offs", firm_id, document_id)
