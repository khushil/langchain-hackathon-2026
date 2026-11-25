"""Earlier decisions in the store, one namespace for each customer, read for carry-over."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from langgraph.store.base import BaseStore
from pydantic import ValidationError

from fsi_common.records import RECORD_TYPES, Record
from utils.kyc_state import decisions_namespace, sign_offs_namespace
from workflow.errors import StoredDecisionError, UnknownSubjectError

PAGE = 100
DECISION_SCHEMA = "decision.v1"


def load_decisions(store: BaseStore, customer_ids: Iterable[str]) -> list[Record]:
    """Read every decision recorded about the given customers, in key order.

    Each customer's namespace is read page by page until it is empty, so no decision is left
    behind.

    Args:
        store: The store the review step writes to.
        customer_ids: The customers whose decisions are wanted.

    Returns:
        The decisions, validated.

    Raises:
        StoredDecisionError: If an item is not a valid decision; the item's key is named.
    """
    decisions = []
    for customer_id in dict.fromkeys(customer_ids):
        namespace = decisions_namespace(customer_id)
        items, offset = [], 0
        while True:
            page = store.search(namespace, limit=PAGE, offset=offset)
            items.extend(page)
            if len(page) < PAGE:
                break
            offset += PAGE
        for item in sorted(items, key=lambda i: i.key):
            try:
                decisions.append(RECORD_TYPES[DECISION_SCHEMA].model_validate(item.value))
            except ValidationError as exc:
                raise StoredDecisionError(
                    f"The stored decision {item.key} about {customer_id} is not valid: {exc}"
                ) from exc
    return decisions


def latest_by_subject(decisions: Iterable[Record]) -> dict[str, Record]:
    """Pick the latest decision on each subject, by date and then by id.

    Args:
        decisions: Decisions, in any order.

    Returns:
        The latest decision for each subject id.
    """
    latest: dict[str, Any] = {}
    for decision in decisions:
        held = latest.get(decision.subject_id)
        if held is None or (decision.date, decision.id) > (held.date, held.id):
            latest[decision.subject_id] = decision
    return latest


def save_decisions(
    store: BaseStore, customers: Mapping[str, str], decisions: Iterable[Record]
) -> None:
    """Keep a reviewer's decisions, each under its id in the namespace of its customer.

    Args:
        store: The store.
        customers: The customer each subject id is about.
        decisions: The decisions received in a review response.

    Raises:
        UnknownSubjectError: If a decision is on a subject no customer is named for.
    """
    for decision in decisions:
        customer = customers.get(decision.subject_id)
        if customer is None:
            raise UnknownSubjectError(
                f"Decision {decision.id} is on {decision.subject_id}, which is about no customer "
                "of this run."
            )
        store.put(decisions_namespace(customer), decision.id, decision.to_json())


def save_sign_off(store: BaseStore, sign_off: Record) -> None:
    """Keep a sign-off, under its id.

    Args:
        store: The store.
        sign_off: The sign-off received in a review response.
    """
    store.put(sign_offs_namespace(), sign_off.id, sign_off.to_json())
