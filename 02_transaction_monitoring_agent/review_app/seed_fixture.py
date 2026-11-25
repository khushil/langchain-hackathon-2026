"""The reviewer's wording for the seed: one decision for each transaction before 19 October.

Every sentence here is the fictional reviewer's, written for the first customer's six
transactions of the recorded run, and goes into the application only through its review routes.
Where the starter scripted a reply for a transaction (``data/reviewer_answers.jsonl``), the
decision and the note are that reply's own words.
"""

from __future__ import annotations

from dataclasses import dataclass

from utils import db

USER_ID = "USR-001"
WINDOW_END = "2026-10-19"
"""The first run reads the transactions before this day; the second reads them all."""


@dataclass(frozen=True)
class SeedDecision:
    """One decision of the fictional reviewer on one transaction, in her words.

    ``proposal`` is what the recorded assessor proposed for the transaction, so that a new
    recording that proposes otherwise is reported by what changed. ``outcome`` is ``accept``
    when she agrees with the proposal and ``amend`` when she gives her own decision, ``final``.
    """

    tx_id: str
    proposal: str
    outcome: str
    reason: str
    final: str | None = None
    wording: str | None = None


def _scripted(tx_id: str) -> tuple[str, str]:
    reply = db.get("reviewer_answers", transaction_id=tx_id)
    return reply["decision"], reply["note"]


_HOLIDAY_DECISION, _HOLIDAY_NOTE = _scripted("TX-1003")

DECISIONS = (
    SeedDecision(
        "TX-1001",
        "approve",
        "accept",
        "A small grocery shop near her home, well inside her usual spend.",
    ),
    SeedDecision("TX-1002", "approve", "accept", "Her usual commute on City Transit."),
    SeedDecision("TX-1003", _HOLIDAY_DECISION, "accept", _HOLIDAY_NOTE),
    SeedDecision(
        "TX-1004",
        "approve",
        "accept",
        "Dinner in Lisbon on the trip she confirmed for the hotel; the euro amount is small.",
    ),
    SeedDecision(
        "TX-1005",
        "block",
        "accept",
        "A crypto exchange at a quarter past two in the morning, almost twenty times the top of "
        "her usual range and in a country she has not told us about.",
    ),
    SeedDecision(
        "TX-1006",
        "block",
        "accept",
        "Gift cards seven minutes after the crypto purchase, on the same pattern.",
    ),
)
