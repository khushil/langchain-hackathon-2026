"""How a fact and its source paragraph are shown: marked quote, labels, and plain words."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from fsi_common.app.rendering import long_date
from fsi_common.records import CheckResult, Decision, Fact, Person, SignOff

ATTRIBUTE_LABELS = {
    "requirement": "Requirement",
    "deadline": "Deadline as written",
    "actor": "Who must act",
    "cross_refs": "Refers to",
    "conditions": "Conditions",
    "field": "Field",
    "value": "Value",
    "small_firm": "Small firm",
    "provider_id": "Provider",
    "contract_end": "Contract ends",
    "material": "Material",
}
KIND_LABELS = {
    "obligation": "Obligation",
    "permission": "Permission",
    "guidance": "Guidance",
    "definition": "Definition",
    "scope": "Scope",
    "effective_date": "Effective date",
    "regulator_action": "Regulator action",
    "context": "Context",
    "firm_attribute": "Firm detail",
    "provider_attribute": "Provider detail",
}
CHECK_LABELS = {
    "quote-verbatim": "The quote is word for word in the paragraph",
    "deadline-verbatim": "The deadline is word for word in the paragraph",
}
OUTCOME_WORDS = {
    "accept": "Accepted",
    "amend": "Amended",
    "reject": "Rejected",
    "answer": "Answered",
}
NONE_STATED = "None stated in the paragraph"
NONE_NAMED = "none named"
"""What a missing value of a firm or provider table reads."""
DOES_NOT_APPLY = "Does not apply"
"""What the Requirement and Deadline columns read for a fact about a table row, not a paragraph."""


@dataclass(frozen=True)
class Segment:
    """A run of the paragraph's text, marked when it is the quoted words."""

    text: str
    marked: bool


def mark_quote(text: str, quote: str) -> tuple[Segment, ...] | None:
    """Split a paragraph around the first place the quote occurs word for word.

    White space may differ between the two; the words may not.

    Args:
        text: The paragraph as read.
        quote: The fact's quote.

    Returns:
        The segments in order, or None when the quote is not in the paragraph.
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


def anchor_label(anchor: str) -> str:
    """Name a place in a source in words: ``para:7.1`` becomes ``Paragraph 7.1``.

    Args:
        anchor: The anchor.

    Returns:
        The place in words.
    """
    scheme, _, rest = anchor.partition(":")
    names = {"para": "Paragraph", "row": "Row"}
    return f"{names.get(scheme, scheme.capitalize())} {rest}"


def place_of(cited: object) -> str:
    """Name a cited fact by its place and kind: ``Paragraph 7.1, obligation``.

    Args:
        cited: A ``CitedFact``.

    Returns:
        The words that name the fact on a link.
    """
    fact = cited.fact  # type: ignore[attr-defined]
    return f"{anchor_label(fact.subject.anchor)}, {kind_label(fact.kind).lower()}"


def attribute_label(key: str) -> str:
    """Return the label of an attribute, or the key in words when no label is held."""
    return ATTRIBUTE_LABELS.get(key, key.replace("_", " ").capitalize())


def unmapped_attribute_keys(facts: Iterable[Fact]) -> set[str]:
    """Return the attribute keys that have no label.

    Args:
        facts: The facts to look through.

    Returns:
        The keys with no entry in ``ATTRIBUTE_LABELS``.
    """
    return {key for fact in facts for key in fact.attributes} - set(ATTRIBUTE_LABELS)


def kind_label(kind: str) -> str:
    """Return a fact kind in words."""
    return KIND_LABELS.get(kind, kind.replace("_", " ").capitalize())


def attribute_value(value: object, *, missing: str = NONE_STATED) -> str:
    """Write an attribute's value as a person reads it.

    Args:
        value: A normalised attribute value.
        missing: What a missing value reads; a paragraph's by default, a table row's by choice.

    Returns:
        The words; a missing value is said to be missing.
    """
    if value is None:
        return missing
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else missing
    return str(value)


def requirements_text(value: object) -> str:
    """Write a fact's requirements as a person reads them, each one, in the order held.

    Args:
        value: The ``requirement`` attribute: a list of requirements, or one requirement.

    Returns:
        One requirement as it is; several numbered in order, such as ``(1) A; (2) B``; and a
        missing one said to be missing.
    """
    if isinstance(value, list):
        if not value:
            return NONE_STATED
        if len(value) == 1:
            return str(value[0])
        return "; ".join(f"({n}) {item}" for n, item in enumerate(value, 1))
    return attribute_value(value)


def attribute_rows(fact: Fact) -> list[tuple[str, str]]:
    """Return a fact's attributes as label and value pairs, in key order.

    Args:
        fact: The fact.

    Returns:
        The pairs; the requirements are written one after another in the order the fact holds.
    """
    return [
        (attribute_label(k), requirements_text(v) if k == "requirement" else attribute_value(v))
        for k, v in sorted(fact.attributes.items())
    ]


def check_label(check: CheckResult) -> str:
    """Name a check in words, without its version."""
    base = check.check.rsplit(".v", 1)[0]
    return CHECK_LABELS.get(base, base.replace("-", " ").capitalize())


def difference_label(path: str) -> str:
    """Name a changed judged field in words: ``attributes.deadline`` becomes the deadline label."""
    head, _, rest = path.partition(".")
    if head == "attributes":
        return attribute_label(rest)
    if head == "checks":
        return check_label(CheckResult(check=rest, outcome="pass", detail="-")) + " (result)"
    return {"quote": "The quoted words", "kind": "The kind", "subject": "The paragraph"}.get(
        head, head.replace("_", " ").capitalize()
    )


def outcome_word(decision: Decision) -> str:
    """Return what a decision was in one word, such as ``Accepted`` or ``Amended``."""
    return OUTCOME_WORDS[decision.outcome]


def by_whom(decision: Decision, viewer: Person | None = None) -> str:
    """Name who made a decision: ``you`` only when they are the person signed in.

    Args:
        decision: The decision.
        viewer: The person signed in, or None when nobody is.

    Returns:
        ``you`` when the decision's reviewer is the viewer, otherwise the reviewer's name and role.
    """
    if viewer is not None and decision.reviewer == viewer:
        return "you"
    return f"{decision.reviewer.name}, {decision.reviewer.role}"


def decision_by(decision: Decision, viewer: Person | None = None) -> str:
    """Say what was decided and by whom, such as ``Accepted by Dana Whitfield, Head of Compliance``.

    Args:
        decision: The decision.
        viewer: The person signed in, or None when nobody is.

    Returns:
        The outcome and the reviewer, with ``you`` only for the viewer's own decision.
    """
    return f"{outcome_word(decision)} by {by_whom(decision, viewer)}"


def decision_line(decision: Decision, viewer: Person | None = None) -> str:
    """Say who decided what and when, in one line.

    Args:
        decision: The decision.
        viewer: The person signed in, or None when nobody is.

    Returns:
        For example ``Accepted by Dana Whitfield, Head of Compliance, on 25 November 2026``, with
        ``you`` for the reviewer only when the reviewer is the viewer.
    """
    return f"{decision_by(decision, viewer)}, on {long_date(decision.date)}"


def sentence_end(text: str) -> str:
    """Give a person's words a full stop unless they already end with a mark that closes one.

    Args:
        text: The words, such as an amended wording a reviewer wrote.

    Returns:
        The words, trimmed, ending in one full stop, question mark or exclamation mark.
    """
    words = text.strip()
    return words if words.endswith((".", "?", "!")) else f"{words}."


def pick_decision(candidates: list[Decision], sign_off: SignOff | None) -> Decision | None:
    """Choose the decision a finished brief stands on when a fact has more than one.

    The one made by the sign-off's reviewer on the sign-off's date stands; failing that, the
    latest by date, and of two on one date the one the run recorded later.

    Args:
        candidates: Every decision on one fact or question, in the order the run holds them.
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
