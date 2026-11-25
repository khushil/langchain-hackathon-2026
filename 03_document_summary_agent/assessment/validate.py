"""The plain-code checks of a bundle: quotes word for word, all assessed, every clause placed.

``validate_bundle`` runs every check and returns every fault, each named by its check, so a
planted fault is found by name. ``require_valid`` raises when there is any.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from assessment.provisions import derive_state
from assessment.records import RELATIONS, Bundle
from assessment.texts import TextIndex
from context.errors import ContextError

CHECKS = (
    "clause-quote-not-verbatim",
    "provision-quote-not-verbatim",
    "applicable-obligation-not-assessed",
    "inapplicable-obligation-assessed",
    "clause-neither-mapped-nor-listed",
    "not-covered-without-second-look",
    "superseded-clause-covers",
    "graph-fact-subject-quote",
    "graph-fact-object-quote",
    "derived-state-mismatch",
    "points-incomplete",
    "compliance-words",
    "gap-missing",
    "register-unit-unaccounted",
    "evidence-missing",
    "judgement-missing",
    "seed-match-wrong",
    "partial-scope",
    "state-without-clause",
)
"""Every check's name; each fault carries one."""

COMPLIANCE_WORDS = re.compile(r"\b(non-?)?complian(t|ce)\b|\bcompl(y|ies|ied|ying)\b", re.I)
"""Words that say an institution complies or does not; the product says what documents state."""


class BundleInvalidError(ContextError):
    """A bundle failed one or more of the plain-code checks; the message names each fault."""


@dataclass(frozen=True)
class Fault:
    """One failed check: its name, where, and what was found."""

    check: str
    where: str
    detail: str


@dataclass(frozen=True)
class BundleReport:
    """Every fault of a bundle, and the line that states the outcome."""

    faults: list[Fault] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def line(self) -> str:
        """The outcome in words."""
        if self.faults:
            names = ", ".join(sorted({f.check for f in self.faults}))
            return f"invalid: {len(self.faults)} fault(s) ({names})"
        parts = ", ".join(f"{v} {k}" for k, v in self.counts.items())
        return f"valid: {parts}"


def _assessment_checks(bundle: Bundle, texts: TextIndex, faults: list[Fault]) -> None:
    register = bundle.obligation_register
    for a in bundle.assessments:
        obligation = register.obligation(a.obligation_id)
        where = a.obligation_id
        if obligation is None:
            faults.append(Fault("evidence-missing", where, "no such obligation in the register"))
            continue
        if not texts.provision_has(a.regulation, obligation.anchor, a.provision_quote):
            faults.append(Fault("provision-quote-not-verbatim", where, a.provision_quote[:80]))
        quotes = list(a.clause_quotes) + [q for p in a.points for q in p.clause_quotes]
        for q in quotes:
            if not texts.clause_has(q.clause.document, q.clause.clause, q.quote):
                faults.append(
                    Fault(
                        "clause-quote-not-verbatim", where, f"{q.clause.document} {q.clause.clause}"
                    )
                )
            if a.state in ("covered", "in conflict") and not texts.in_force(q.clause.document):
                faults.append(
                    Fault("superseded-clause-covers", where, f"{q.clause.document} is not in force")
                )
        if a.state != "not covered" and not a.clause_quotes:
            faults.append(Fault("state-without-clause", where, f"{a.state} cites no clause"))
        if a.state != "covered" and not (a.gap or "").strip():
            faults.append(Fault("gap-missing", where, f"state {a.state} with no gap in words"))
        for p in a.points:
            if p.state != "covered" and not (p.gap or "").strip():
                faults.append(Fault("gap-missing", f"{where} point {p.point}", p.state))
        if obligation.points:
            given = [p.point for p in a.points]
            if sorted(given) != sorted(obligation.points):
                faults.append(Fault("points-incomplete", where, f"{given} for {obligation.points}"))
            elif derive_state(p.state for p in a.points) != a.state:
                faults.append(Fault("derived-state-mismatch", where, a.state))
        kept = [c for c in bundle.candidates if c.obligation_id == where and c.kept]
        if a.state == "not covered" and not kept and not a.second_look:
            faults.append(Fault("not-covered-without-second-look", where, "no candidate, no look"))
        facts = {f.id for f in bundle.facts}
        if any(e not in facts for e in a.evidence):
            faults.append(Fault("evidence-missing", where, "an evidence fact is not in the bundle"))
        if a.assessed_by == "model" and not any(
            j.request.obligation_id == where for j in bundle.judgements
        ):
            faults.append(Fault("judgement-missing", where, "assessed by model with no judgement"))
        texts_said = [a.gap or "", a.suggested_wording or ""] + [p.gap or "" for p in a.points]
        if any(COMPLIANCE_WORDS.search(t) for t in texts_said):
            faults.append(Fault("compliance-words", where, "says a firm complies or does not"))


def _coverage_checks(bundle: Bundle, texts: TextIndex, faults: list[Fault]) -> None:
    register = bundle.obligation_register
    assessed = Counter(a.obligation_id for a in bundle.assessments)
    scope = set(bundle.index.scope)
    if scope and bundle.index.run != "fake":
        faults.append(Fault("partial-scope", bundle.index.run, f"{len(scope)} obligations only"))
    for o in register.obligations:
        in_scope = not scope or o.obligation_id in scope
        if in_scope and o.applies is True and assessed[o.obligation_id] != 1:
            faults.append(
                Fault(
                    "applicable-obligation-not-assessed",
                    o.obligation_id,
                    f"{assessed[o.obligation_id]} assessments",
                )
            )
        if o.applies is not True and assessed[o.obligation_id]:
            faults.append(Fault("inapplicable-obligation-assessed", o.obligation_id, o.reason))
    placed = {(m.clause.document, m.clause.clause): m for m in bundle.clause_map}
    for document, clauses in texts.clauses.items():
        if not texts.in_force(document):
            continue
        for clause in clauses:
            mapping = placed.get((document, clause.number))
            if mapping is None or (
                not mapping.obligations and not (mapping.unmapped_reason or "").strip()
            ):
                faults.append(
                    Fault(
                        "clause-neither-mapped-nor-listed", f"{document} {clause.number}", "absent"
                    )
                )
    for key, read in texts.regulations.items():
        anchors = Counter(d.anchor for d in register.dispositions if d.regulation == key)
        units = Counter(u.anchor for u in read.items)
        if anchors != units:
            faults.append(
                Fault(
                    "register-unit-unaccounted",
                    key,
                    f"{sum(anchors.values())} of {sum(units.values())}",
                )
            )


def _graph_checks(bundle: Bundle, texts: TextIndex, faults: list[Fault]) -> None:
    for f in bundle.facts:
        if f.kind not in RELATIONS:
            continue
        where = f"{f.kind} {f.subject.anchor}"
        if not texts.quote_at(f.subject.source_id, f.subject.anchor, f.quote):
            faults.append(Fault("graph-fact-subject-quote", where, f.quote[:80]))
        attrs = f.attributes
        if not texts.quote_at(
            str(attrs.get("object_source_id")),
            str(attrs.get("object_anchor")),
            str(attrs.get("object_quote")),
        ):
            faults.append(
                Fault("graph-fact-object-quote", where, str(attrs.get("object_quote"))[:80])
            )


def _report_checks(bundle: Bundle, faults: list[Fault]) -> None:
    for s in bundle.gap_report.statements:
        if COMPLIANCE_WORDS.search(s.text):
            faults.append(Fault("compliance-words", "gap report", s.text[:80]))
    by_id = {a.obligation_id: a for a in bundle.assessments}
    for m in bundle.seed_matches:
        found = [by_id[o].state for o in m.obligation_ids if o in by_id]
        if len(found) != len(m.obligation_ids):
            faults.append(Fault("seed-match-wrong", m.seed_id, "an obligation is not assessed"))
            continue
        if m.points and len(m.obligation_ids) == 1:
            a = by_id[m.obligation_ids[0]]
            point = next((p for p in a.points if p.point == m.points[0]), None)
            expected = point.state if point else a.state
        else:
            expected = derive_state(found)
        if expected != m.found_state:
            faults.append(Fault("seed-match-wrong", m.seed_id, f"{m.found_state} for {expected}"))


def validate_bundle(bundle: Bundle, texts: TextIndex) -> BundleReport:
    """Run every plain-code check on a bundle.

    Args:
        bundle: The bundle.
        texts: The regulations and corpus the bundle was built from.

    Returns:
        Every fault, and the counts of what was checked.
    """
    faults: list[Fault] = []
    _assessment_checks(bundle, texts, faults)
    _coverage_checks(bundle, texts, faults)
    _graph_checks(bundle, texts, faults)
    _report_checks(bundle, faults)
    counts = {
        "assessments": len(bundle.assessments),
        "candidates": len(bundle.candidates),
        "facts": len(bundle.facts),
        "clauses placed": len(bundle.clause_map),
        "seeds matched": len(bundle.seed_matches),
    }
    return BundleReport(faults=faults, counts=counts)


def require_valid(bundle: Bundle, texts: TextIndex) -> BundleReport:
    """Run every check and raise on any fault.

    Args:
        bundle: The bundle.
        texts: The regulations and corpus.

    Returns:
        The report, when there is no fault.

    Raises:
        BundleInvalidError: If any check fails; the message names each fault's check and place.
    """
    report = validate_bundle(bundle, texts)
    if report.faults:
        listed = "; ".join(f"{f.check} at {f.where}: {f.detail}" for f in report.faults)
        raise BundleInvalidError(f"The bundle of {bundle.index.corpus} is {report.line}: {listed}.")
    return report
