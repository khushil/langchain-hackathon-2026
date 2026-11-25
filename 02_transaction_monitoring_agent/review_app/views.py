"""How an assessment, its source line and a decision are shown: plain words, never codes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from fsi_common.app.rendering import long_date
from fsi_common.records import CheckResult, Decision, Fact, Person
from utils.review import CitedFact, ReviewStatement, final_of

OUTCOME_WORDS = {
    "accept": "Agreed",
    "amend": "Changed",
    "reject": "Disagreed",
    "answer": "Answered",
}
CHECK_LABELS = {
    "quote-verbatim": "The quoted fields are word for word in the transaction's line",
    "fields-in-row": "Every quoted field is in the row with that value",
    "score-in-range": "The risk score is a whole number from 0 to 100",
    "decision-follows-score": "The proposed decision follows the score, blocking from 70",
    "confidence-in-range": "Both confidences lie from 0 to 1",
    "confidence-checks": "The starter's checks on the confidence give what was recorded",
}
ATTRIBUTE_LABELS = {
    "risk_score": "Risk score",
    "proposed_decision": "Proposed decision",
    "confidence": "Confidence",
    "model_confidence": "Confidence the assessor gave",
    "confidence_checks": "Why the confidence was lowered",
    "reason": "Reason",
    "merchant": "Merchant",
    "category": "Category",
    "amount": "Amount",
    "currency": "Currency",
    "country": "Country",
    "channel": "Channel",
    "timestamp": "Time",
    "user_id": "Customer",
}


@dataclass(frozen=True)
class Segment:
    """A run of a line of text, marked when it is the quoted words."""

    text: str
    marked: bool


def mark_quote(text: str, quote: str) -> tuple[Segment, ...] | None:
    """Split a line around the first place the quote occurs word for word.

    Args:
        text: The line of the data file.
        quote: The fact's quote.

    Returns:
        The segments in order, or None when the quote is not in the line.
    """
    words = quote.split()
    if not words:
        return None
    found = re.search(r"\s+".join(re.escape(w) for w in words), text)
    if found is None:
        return None
    parts = (
        Segment(text[: found.start()], False),
        Segment(found.group(0), True),
        Segment(text[found.end() :], False),
    )
    return tuple(p for p in parts if p.text)


def when_words(timestamp: str) -> str:
    """Write a timestamp as ``9 October 2026, 21:03``."""
    moment = datetime.fromisoformat(timestamp)
    return f"{moment.day} {moment.strftime('%B %Y')}, {moment:%H:%M}"


def check_label(check: CheckResult) -> str:
    """Name a check in words, without its version."""
    base = check.check.rsplit(".v", 1)[0]
    return CHECK_LABELS.get(base, base.replace("-", " ").capitalize())


def attribute_label(key: str) -> str:
    """Return the label of an attribute, or the key in words when none is held."""
    return ATTRIBUTE_LABELS.get(key, key.replace("_", " ").capitalize())


def difference_label(path: str) -> str:
    """Name a changed judged field in words: ``attributes.reason`` becomes ``Reason``."""
    head, _, rest = path.partition(".")
    if head == "attributes":
        return attribute_label(rest)
    if head == "checks":
        return check_label(CheckResult(check=rest, outcome="pass", detail="-")) + " (result)"
    return {"quote": "The quoted fields", "kind": "The kind", "subject": "The transaction"}.get(
        head, head.replace("_", " ").capitalize()
    )


def outcome_word(decision: Decision) -> str:
    """Return what a decision was in one word, such as ``Agreed`` or ``Changed``."""
    return OUTCOME_WORDS[decision.outcome]


def by_whom(decision: Decision, viewer: Person | None = None) -> str:
    """Name who made a decision: ``you`` only when they are the person signed in."""
    if viewer is not None and decision.reviewer == viewer:
        return "you"
    return f"{decision.reviewer.name}, {decision.reviewer.role}"


def decision_by(decision: Decision, viewer: Person | None = None) -> str:
    """Say what was decided and by whom, for example ``Agreed by Sam Okafor, Fraud Analyst``."""
    return f"{outcome_word(decision)} by {by_whom(decision, viewer)}"


def decision_line(decision: Decision, viewer: Person | None = None) -> str:
    """Say who decided what and when, in one line."""
    return f"{decision_by(decision, viewer)}, on {long_date(decision.date)}"


def sentence_end(text: str) -> str:
    """Give a person's words a full stop unless they already end with a mark that closes one."""
    words = text.strip()
    return words if words.endswith((".", "?", "!")) else f"{words}."


def final_word(decision: Decision) -> str:
    """Say the decision a person stands on for a transaction, from their decision on it.

    Args:
        decision: A decision on an assessment.

    Returns:
        ``Proposal agreed`` for an accept, ``Approve`` or ``Block`` for a change, and
        ``Proposal disagreed with`` for a rejection.
    """
    if decision.outcome == "accept":
        return "Proposal agreed"
    if decision.outcome == "amend":
        return (final_of(decision.amendment) or "changed").capitalize()
    return "Proposal disagreed with"


@dataclass(frozen=True)
class AssessmentView:
    """One assessment as the page shows it, with the profile facts its statement cites."""

    cited: CitedFact
    tx_id: str
    when: str
    merchant: str
    category: str
    amount: str
    where: str
    score: str
    proposed: str
    confidence: str
    assessor_confidence: str
    lowered_because: tuple[str, ...]
    reason: str
    home_country: str
    usual_spend: str
    segments: tuple[Segment, ...] | None

    @property
    def fact(self) -> Fact:
        """The assessment fact."""
        return self.cited.fact

    @property
    def lowered(self) -> bool:
        """Whether the starter's checks lowered the confidence."""
        return self.confidence != self.assessor_confidence

    @property
    def checks(self) -> list[tuple[str, bool, str]]:
        """Each check as its words, whether it passed and what it found."""
        return [(check_label(c), c.outcome == "pass", c.detail) for c in self.fact.checks]


def assessment_view(statement: ReviewStatement, cited: CitedFact) -> AssessmentView:
    """Build what the page shows for one assessment of a statement.

    Args:
        statement: The statement that cites the assessment.
        cited: The cited assessment.

    Returns:
        The view, with the customer's home country and usual spend from the facts the statement
        also cites.
    """
    fact = cited.fact
    a = fact.attributes
    profile = {
        c.fact.attributes["field"]: c.fact
        for c in statement.facts
        if c.fact.kind == "customer_attribute"
    }
    home = profile.get("home_country")
    currency = profile.get("currency")
    spend = profile.get("usual_amount_range")
    return AssessmentView(
        cited=cited,
        tx_id=fact.subject.anchor.partition(":")[2],
        when=when_words(str(a["timestamp"])),
        merchant=str(a["merchant"]),
        category=str(a["category"]),
        amount=f"{a['amount']} {a['currency']}",
        where=f"{a['country']}, {str(a['channel']).replace('_', ' ')}",
        score=str(a["risk_score"]),
        proposed=str(a["proposed_decision"]).capitalize(),
        confidence=str(a["confidence"]),
        assessor_confidence=str(a["model_confidence"]),
        lowered_because=tuple(a["confidence_checks"] or ()),
        reason=str(a["reason"]),
        home_country=str(home.attributes["value"]) if home else "not read",
        usual_spend=(
            f"{spend.attributes['low']} to {spend.attributes['high']} "
            f"{currency.attributes['value'] if currency else ''}".strip()
            if spend
            else "not read"
        ),
        segments=mark_quote(cited.unit_text, fact.quote),
    )


def pick_decision(candidates: list[Decision], sign_off) -> Decision | None:
    """Choose the decision a finished brief stands on when a transaction has more than one.

    The one made by the sign-off's reviewer on the sign-off's date stands; failing that, the
    latest by date, and of two on one date the one the run recorded later.

    Args:
        candidates: Every decision on one transaction or question, in the order the run holds them.
        sign_off: The brief's sign-off, when it has one.

    Returns:
        The decision, or None when there is none.
    """
    if not candidates:
        return None
    if sign_off is not None:
        own = [d for d in candidates if d.reviewer == sign_off.reviewer and d.date == sign_off.date]
        if own:
            return own[-1]
    latest = max(d.date for d in candidates)
    return [d for d in candidates if d.date == latest][-1]


def transaction_of(decision: Decision) -> str:
    """Name the transaction a decision is about, from what the person judged.

    Args:
        decision: A decision on an assessment or on a question about a transaction.

    Returns:
        The transaction's id, for example ``TX-1003``.
    """
    place = decision.judged.get("subject") or decision.judged.get("about") or {}
    return str(place.get("anchor", "")).partition(":")[2]
