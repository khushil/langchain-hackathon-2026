"""The words the pages use for facts, decisions and what changed, in one place."""

from __future__ import annotations

from fsi_common.app.rendering import long_date
from fsi_common.records import CheckResult, Decision, Fact, Person, SignOff

KIND_LABELS = {
    "applicant_name": "Name",
    "birth_date": "Date of birth",
    "nationality": "Nationality",
    "occupation": "Occupation",
    "source_of_funds": "Source of funds",
    "funds_amount": "Amount of funds",
    "relation": "Relation named",
    "screening": "Screening",
    "proposal": "Proposal",
}
ATTRIBUTE_LABELS = {
    "value": "Value",
    "amount": "Amount as written",
    "relation": "Relation",
    "related_name": "Name of the relation",
    "related_office": "Office of the relation",
    "risk_level": "Risk level",
    "decision": "Decision",
    "settled": "Settled by the checks",
    "basis": "Basis",
    "sanctions_match": "Sanctions match",
    "unsettled": "What the checks did not settle",
    "name_checked": "Name checked",
    "list": "List",
    "about": "About",
    "entry_name": "Entry",
    "entry_detail": "Entry's programme or post",
    "entry_dob": "Entry's date of birth",
    "applicant_name": "Applicant's name",
    "applicant_dob": "Applicant's date of birth",
    "name_score": "Name score",
    "relation_name": "Relation's name",
    "relation_score": "Relation's name score",
    "dob_agrees": "Dates of birth agree",
    "strength": "Strength of likeness",
    "outcome": "How it ended",
    "settled_by": "Settled by",
    "why_unsettled": "Why the checks did not settle it",
    "reading_same": "Supports the same person",
    "reading_different": "Supports a different person",
}
CHECK_LABELS = {
    "quote-verbatim": "The quote is word for word in the application",
    "name-verbatim": "The name is written in the application",
    "date-reads-as": "The date reads as the date given",
    "amount-verbatim": "The amount is written in the application",
    "words-verbatim": "The words are written in the application",
    "name-score": "The score is the measure of the two names",
    "dob-comparison": "The comparison of dates of birth is right",
    "proposal-follows-checks": "The proposal is what the checks give",
}
OUTCOME_WORDS = {
    "accept": "Accepted",
    "amend": "Amended",
    "reject": "Rejected",
    "answer": "Answered",
}
LISTS = {"sanctions": "Sanctions list", "pep": "PEP list"}


def kind_label(kind: str) -> str:
    """Return a fact kind in words."""
    return KIND_LABELS.get(kind, kind.replace("_", " ").capitalize())


def attribute_label(key: str) -> str:
    """Return the label of an attribute, or the key in words when no label is held."""
    return ATTRIBUTE_LABELS.get(key, key.replace("_", " ").capitalize())


def attribute_value(value: object, *, missing: str = "None") -> str:
    """Write an attribute's value as a person reads it."""
    if value is None:
        return missing
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return "; ".join(str(v) for v in value) if value else missing
    return str(value)


def check_label(check: CheckResult) -> str:
    """Name a check in words, without its version."""
    base = check.check.rsplit(".v", 1)[0]
    return CHECK_LABELS.get(base, base.replace("-", " ").capitalize())


def attribute_rows(fact: Fact) -> list[tuple[str, str]]:
    """Return a fact's attributes as label and value pairs, in key order."""
    return [(attribute_label(k), attribute_value(v)) for k, v in sorted(fact.attributes.items())]


def difference_label(path: str) -> str:
    """Name a changed judged field in words: ``attributes.basis`` becomes ``Basis``."""
    head, _, rest = path.partition(".")
    if head == "attributes":
        return attribute_label(rest)
    if head == "checks":
        return check_label(CheckResult(check=rest, outcome="pass", detail="-")) + " (result)"
    return {"quote": "The quoted words", "kind": "The kind", "subject": "The application"}.get(
        head, head.replace("_", " ").capitalize()
    )


def outcome_word(decision: Decision) -> str:
    """Return what a decision was in one word, such as ``Accepted``."""
    return OUTCOME_WORDS[decision.outcome]


def by_whom(decision: Decision, viewer: Person | None = None) -> str:
    """Name who made a decision: ``you`` only when they are the person signed in."""
    if viewer is not None and decision.reviewer == viewer:
        return "you"
    return f"{decision.reviewer.name}, {decision.reviewer.role}"


def decision_by(decision: Decision, viewer: Person | None = None) -> str:
    """Say what was decided and by whom: ``Accepted by Dana Whitfield, Head of Compliance``."""
    return f"{outcome_word(decision)} by {by_whom(decision, viewer)}"


def decision_line(decision: Decision, viewer: Person | None = None) -> str:
    """Say who decided what and when, in one line."""
    return f"{decision_by(decision, viewer)}, on {long_date(decision.date)}"


def sentence_end(text: str) -> str:
    """Give a person's words a full stop unless they already end with a mark that closes one."""
    words = text.strip()
    return words if words.endswith((".", "?", "!")) else f"{words}."


def proposal_words(fact: Fact) -> str:
    """Say a proposal in words: ``High risk, reject``."""
    risk, decision = fact.attributes["risk_level"], fact.attributes["decision"]
    return f"{str(risk).capitalize()} risk, {decision}"


def pick_decision(candidates: list[Decision], sign_off: SignOff | None) -> Decision | None:
    """Choose the decision a finished batch stands on when a subject has more than one.

    The one made by the sign-off's reviewer on the sign-off's date stands; failing that, the
    latest by date, and of two on one date the one the run recorded later.
    """
    if not candidates:
        return None
    if sign_off is not None:
        own = [d for d in candidates if d.reviewer == sign_off.reviewer and d.date == sign_off.date]
        if own:
            return own[-1]
    latest = max(d.date for d in candidates)
    return [d for d in candidates if d.date == latest][-1]
