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
    judged_differences,
    judged_digest,
)


def _addressed(records: Iterable[Record]) -> Iterator[Addressed]:
    for record in records:
        yield record
        if isinstance(record, Brief):
            yield from record.statements


def _references(record: Record) -> Iterator[tuple[str, str, str | None]]:
    """Yield each id a record cites, with the judged digest it must have where it names one."""
    if isinstance(record, Fact):
        yield "subject.source_id", record.subject.source_id, None
    elif isinstance(record, (SourceUnit, UnitAccounting)):
        yield "source_id", record.source_id, None
    elif isinstance(record, Brief):
        yield from (("sources", ref, None) for ref in record.sources)
        yield from (("open_question_ids", ref, None) for ref in record.open_question_ids)
        for statement in record.statements:
            yield from ((f"{statement.id}.cites", ref, None) for ref in statement.cites)
    elif isinstance(record, OpenQuestion):
        yield "about.source_id", record.about.source_id, None
        yield from (("cites", ref, None) for ref in record.cites)
        if record.decision_id:
            yield "decision_id", record.decision_id, None
    elif isinstance(record, Disagreement):
        yield from (("claims", c.fact_id, c.judged_digest) for c in record.claims)
        if record.decision_id:
            yield "decision_id", record.decision_id, None
    elif isinstance(record, Decision):
        yield "subject_id", record.subject_id, None
    elif isinstance(record, SignOff):
        yield "brief_id", record.brief_id, None
        yield from (("assumptions", a.question_id, None) for a in record.assumptions)


def _variants_side_by_side(items: list[Addressed], records: list[Record]) -> bool:
    """Whether different contents under one id are facts a disagreement keeps side by side."""
    if not all(isinstance(item, Fact) for item in items):
        return False
    needed = {(item.id, judged_digest(item)) for item in items}
    return any(
        isinstance(record, Disagreement)
        and needed <= {(c.fact_id, c.judged_digest) for c in record.claims}
        for record in records
    )


def check_bundle(records: list[Record], *, where: str) -> list[Finding]:
    """Run the checks that need several records together.

    Two different contents under one id are refused, except two or more facts that a
    disagreement in the bundle names by id and judged digest, which are kept side by side.

    Args:
        records: Every record of one bundle, each already valid on its own.
        where: The bundle's file, for the findings.

    Returns:
        The findings.
    """
    findings: list[Finding] = []
    by_id: dict[str, list[Addressed]] = {}
    for item in _addressed(records):
        held = by_id.setdefault(item.id, [])
        if all(earlier.to_json() != item.to_json() for earlier in held):
            held.append(item)
    for item_id, items in by_id.items():
        if len(items) > 1 and not _variants_side_by_side(items, records):
            findings.append(
                Finding("id.duplicate", f"{where} {item_id}", "two different records share the id")
            )
    for record in records:
        for field, ref, judged in _references(record):
            held = by_id.get(ref, [])
            if not held or (judged and all(judged_digest(item) != judged for item in held)):
                shown = f"{ref} judged {judged}" if judged else ref
                findings.append(
                    Finding(
                        "ref.resolves",
                        f"{where} {record.id}.{field}",
                        f"{shown} is not in the bundle",
                    )
                )
    findings += _decision_checks(records, by_id, where)
    findings += _brief_checks(records, by_id, where)
    findings += _accounting_checks(records, where)
    return findings


def _decision_checks(
    records: list[Record], by_id: dict[str, list[Addressed]], where: str
) -> list[Finding]:
    findings = []
    for record in records:
        if isinstance(record, Decision) and record.subject_id in by_id:
            subjects = by_id[record.subject_id]
            if all(judged_digest(item) != record.judged_digest for item in subjects):
                changed = judged_differences(record.judged, subjects[0].judged_basis())
                findings.append(
                    Finding(
                        "decision.digest-stale",
                        f"{where} {record.id}",
                        f"judged {record.judged_digest}, the subject now gives "
                        f"{judged_digest(subjects[0])}; changed: {', '.join(changed)}",
                    )
                )
        if isinstance(record, OpenQuestion) and record.decision_id in by_id:
            decision = by_id[record.decision_id][0]
            if not isinstance(decision, Decision) or decision.subject_id != record.id:
                findings.append(
                    Finding(
                        "question.decision-matches",
                        f"{where} {record.id}",
                        f"{record.decision_id} is not about it",
                    )
                )
    return findings


def _brief_checks(
    records: list[Record], by_id: dict[str, list[Addressed]], where: str
) -> list[Finding]:
    findings = []
    for record in records:
        if isinstance(record, Brief):
            for statement in record.statements:
                for ref in statement.cites:
                    held = by_id.get(ref, [])
                    if any(isinstance(f, Fact) and not f.passed_checks for f in held):
                        findings.append(
                            Finding(
                                "brief.cites-failed-check",
                                f"{where} {statement.id}",
                                f"{ref} failed a check",
                            )
                        )
        brief = by_id.get(record.brief_id, [None])[0] if isinstance(record, SignOff) else None
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
                    question = by_id.get(ref, [None])[0]
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
