"""Builders the tests share: a small stream of facts, a request over them, and a decision."""

from __future__ import annotations

from dataclasses import dataclass

from context.checks import RecordedAssessment
from context.facts import assessment_fact, customer_facts
from context.reader import StreamRead, read_stream
from fsi_common.records import Brief, Decision, Fact, SignOff, record_digest
from tools.decisions import _confidence_checks
from utils import db
from utils.records import FACT_CONTEXT
from utils.review import (
    CitedFact,
    Customer,
    ReviewRequest,
    ReviewStatement,
)

DANA = {"name": "Dana Whitfield", "role": "Head of Compliance"}
TODAY = "2026-11-25"


def recorded_for(tx_id: str, score: int, *, reason: str = "") -> RecordedAssessment:
    """Return the proposal a careful assessor would record: the starter's rule, checks applied."""
    row = db.get("transactions", transaction_id=tx_id)
    fired = _confidence_checks(score, row, row["user_id"], (30, 70))
    model_confidence = 0.9
    return RecordedAssessment(
        transaction_id=tx_id,
        risk_score=score,
        model_confidence=model_confidence,
        confidence=min(model_confidence, 0.5) if fired else model_confidence,
        confidence_checks=fired,
        agent_decision="block" if score >= 70 else "approve",
        reason=reason or f"Proposed from a score of {score}.",
    )


def assessment(stream: StreamRead, tx_id: str, score: int, *, reason: str = "") -> Fact:
    """Build the assessment fact of one transaction of a stream."""
    row = db.get("transactions", transaction_id=tx_id)
    return assessment_fact(
        stream,
        row,
        recorded_for(tx_id, score, reason=reason),
        model="claude-sonnet-5-5",
        prompt_version="assessor-1",
        observed_on=TODAY,
    )


@dataclass(frozen=True)
class Small:
    """Two assessments and the customer's facts, with a review request over them."""

    stream: StreamRead
    facts: dict[str, Fact]
    request: ReviewRequest
    brief: Brief


def small_request(*, carry_from: dict[str, Decision] | None = None) -> Small:
    """Build a review request for USR-001's TX-1001 and TX-1003, with no earlier decision."""
    from context.facts import customer_facts as _customer
    from fsi_common.records import carry_over

    stream = read_stream("USR-001", end="2026-10-10")
    scores = {"TX-1001": 5, "TX-1003": 45}
    assessments = {t: assessment(stream, t, s) for t, s in scores.items()}
    profile = {f.attributes["field"]: f for f in _customer(stream)}
    facts = {f.id: f for f in [*assessments.values(), *profile.values()]}
    earlier = carry_from or {}
    statements = []
    for tx_id, fact in assessments.items():
        cited = [fact, profile["home_country"], profile["usual_amount_range"]]
        statements.append(
            ReviewStatement(
                statement_id="statement:" + "0" * 16,
                heading=None,
                text=f"{tx_id} proposed {fact.attributes['proposed_decision']}.",
                facts=[
                    CitedFact(
                        fact=f,
                        seen_digest=record_digest(f),
                        unit_text=stream.unit_text[stream.unit_of[f.subject.anchor].id],
                        carry=carry_over(earlier.get(f.id), f),
                    )
                    for f in cited
                ],
            )
        )
    request = ReviewRequest(
        brief_id="brief:" + "1" * 16,
        brief_digest="sha256:" + "2" * 64,
        request="Assess USR-001",
        customer=Customer(user_id="USR-001", name="Priya Shah"),
        statements=statements,
        open_questions=[],
        history=[],
    )
    return Small(stream, facts, request, None)  # type: ignore[arg-type]


def accept(fact: Fact, *, reason: str = "Matches what the customer told us.") -> Decision:
    """Build a decision as the review route would, for a test's reviewer Dana Whitfield."""
    return Decision.on(fact, outcome="accept", reason=reason, reviewer=DANA, date=TODAY)


__all__ = ["DANA", "FACT_CONTEXT", "TODAY", "SignOff", "accept", "assessment", "customer_facts"]
