"""The checks that need several records together: references, digests seen and counts that close."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from fsi_common.checks import Finding
from fsi_common.records import (
    SETTLED_STATES,
    Addressed,
    Brief,
    Decision,
    Disagreement,
    Fact,
    OpenQuestion,
    Record,
    SignOff,
    SourceUnit,
    UnitAccounting,
    record_digest,
)


def _addressed(records: Iterable[Record]) -> Iterator[Addressed]:
    for record in records:
        yield record
        if isinstance(record, Brief):
            yield from record.statements


def _references(record: Record) -> Iterator[tuple[str, str]]:
    if isinstance(record, Fact):
        yield "subject.source_id", record.subject.source_id
    elif isinstance(record, (SourceUnit, UnitAccounting)):
        yield "source_id", record.source_id
    elif isinstance(record, Brief):
        yield from (("sources", ref) for ref in record.sources)
        yield from (("open_question_ids", ref) for ref in record.open_question_ids)
        for statement in record.statements:
            yield from ((f"{statement.id}.cites", ref) for ref in statement.cites)
    elif isinstance(record, OpenQuestion):
        yield "about.source_id", record.about.source_id
        yield from (("cites", ref) for ref in record.cites)
        if record.decision_id:
            yield "decision_id", record.decision_id
    elif isinstance(record, Disagreement):
        yield from (("claims", ref) for ref in record.claims)
        if record.decision_id:
            yield "decision_id", record.decision_id
    elif isinstance(record, Decision):
        yield "subject_id", record.subject_id
    elif isinstance(record, SignOff):
        yield "brief_id", record.brief_id
        yield from (("assumptions", a.question_id) for a in record.assumptions)


def check_bundle(records: list[Record], *, where: str) -> list[Finding]:
    """Run the checks that need several records together.

    Args:
        records: Every record of one bundle, each already valid on its own.
        where: The bundle's file, for the findings.

    Returns:
        The findings.
    """
    findings: list[Finding] = []
    by_id: dict[str, Addressed] = {}
    for item in _addressed(records):
        earlier = by_id.get(item.id)
        if earlier is not None and earlier.to_json() != item.to_json():
            findings.append(
                Finding("id.duplicate", f"{where} {item.id}", "two different records share the id")
            )
        by_id.setdefault(item.id, item)
    for record in records:
        for field, ref in _references(record):
            if ref not in by_id:
                findings.append(
                    Finding(
                        "ref.resolves",
                        f"{where} {record.id}.{field}",
                        f"{ref} is not in the bundle",
                    )
                )
    findings += _decision_checks(records, by_id, where)
    findings += _brief_checks(records, by_id, where)
    findings += _accounting_checks(records, where)
    return findings


def _decision_checks(
    records: list[Record], by_id: dict[str, Addressed], where: str
) -> list[Finding]:
    findings = []
    for record in records:
        if isinstance(record, Decision) and record.subject_id in by_id:
            seen = record_digest(by_id[record.subject_id])
            if record.seen_digest != seen:
                findings.append(
                    Finding(
                        "decision.digest-stale",
                        f"{where} {record.id}",
                        f"seen {record.seen_digest}, record is {seen}",
                    )
                )
        if isinstance(record, OpenQuestion) and record.decision_id in by_id:
            decision = by_id[record.decision_id]
            if not isinstance(decision, Decision) or decision.subject_id != record.id:
                findings.append(
                    Finding(
                        "question.decision-matches",
                        f"{where} {record.id}",
                        f"{record.decision_id} is not about it",
                    )
                )
    return findings


def _brief_checks(records: list[Record], by_id: dict[str, Addressed], where: str) -> list[Finding]:
    findings = []
    for record in records:
        if isinstance(record, Brief):
            for statement in record.statements:
                for ref in statement.cites:
                    fact = by_id.get(ref)
                    if isinstance(fact, Fact) and not fact.passed_checks:
                        findings.append(
                            Finding(
                                "brief.cites-failed-check",
                                f"{where} {statement.id}",
                                f"{ref} failed a check",
                            )
                        )
        brief = by_id.get(record.brief_id) if isinstance(record, SignOff) else None
        if isinstance(record, SignOff) and isinstance(brief, Brief):
            if record.brief_digest != brief.content_digest:
                findings.append(
                    Finding(
                        "signoff.digest-matches",
                        f"{where} {record.id}",
                        f"signed {record.brief_digest}, brief is {brief.content_digest}",
                    )
                )
            accepted = {a.question_id for a in record.assumptions}
            for ref in sorted(accepted - set(brief.open_question_ids)):
                findings.append(
                    Finding(
                        "signoff.assumptions",
                        f"{where} {record.id}",
                        f"{ref} is not carried by the brief",
                    )
                )
            if record.outcome == "signed":
                for ref in brief.open_question_ids:
                    question = by_id.get(ref)
                    settled = (
                        isinstance(question, OpenQuestion) and question.state in SETTLED_STATES
                    )
                    if ref not in accepted and not settled:
                        findings.append(
                            Finding(
                                "signoff.open-question-unrecorded",
                                f"{where} {record.id}",
                                f"{ref} is open and not accepted",
                            )
                        )
    return findings


def _accounting_checks(records: list[Record], where: str) -> list[Finding]:
    findings = []
    for record in records:
        if not isinstance(record, UnitAccounting):
            continue
        cited = {
            f.subject.anchor
            for f in records
            if isinstance(f, Fact) and f.subject.source_id == record.source_id
        }
        listed = set(record.with_facts)
        for anchor in sorted(listed - cited):
            findings.append(
                Finding(
                    "accounting.facts-match",
                    f"{where} {record.id}",
                    f"{anchor} is listed with facts but has none",
                )
            )
        for anchor in sorted(cited - listed):
            findings.append(
                Finding(
                    "accounting.facts-match",
                    f"{where} {record.id}",
                    f"{anchor} has facts but is not listed",
                )
            )
    return findings
