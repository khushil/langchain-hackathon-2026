"""Earlier decisions in the store: read for carry-over, and what a reviewer sends back is kept."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from langgraph.store.base import BaseStore
from pydantic import ValidationError

from fsi_common.records import RECORD_TYPES, Record
from utils.state import decisions_namespace, sign_offs_namespace
from workflow.errors import StoredDecisionError

PAGE = 100
DECISION_SCHEMA = "decision.v1"


def load_decisions(store: BaseStore, firm_id: str, document_id: str) -> list[Record]:
    """Read every decision a firm has recorded on a document, in key order.

    The store is read page by page until it is empty, so no decision is left behind.

    Args:
        store: The store the review step writes to.
        firm_id: The firm.
        document_id: The document's own key.

    Returns:
        The decisions, validated.

    Raises:
        StoredDecisionError: If an item is not a valid decision; the item's key is named.
    """
    namespace = decisions_namespace(firm_id, document_id)
    items, offset = [], 0
    while True:
        page = store.search(namespace, limit=PAGE, offset=offset)
        items.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
    decisions = []
    for item in sorted(items, key=lambda i: i.key):
        try:
            decisions.append(RECORD_TYPES[DECISION_SCHEMA].model_validate(item.value))
        except ValidationError as exc:
            raise StoredDecisionError(
                f"The stored decision {item.key} for {firm_id} on {document_id} is not valid: {exc}"
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
    store: BaseStore, firm_id: str, document_id: str, decisions: Iterable[Record]
) -> None:
    """Keep a reviewer's decisions, each under its id.

    Args:
        store: The store.
        firm_id: The firm.
        document_id: The document's own key.
        decisions: The decisions received in a review response.
    """
    namespace = decisions_namespace(firm_id, document_id)
    for decision in decisions:
        store.put(namespace, decision.id, decision.to_json())


def save_sign_off(store: BaseStore, firm_id: str, document_id: str, sign_off: Record) -> None:
    """Keep a sign-off, under its id.

    Args:
        store: The store.
        firm_id: The firm.
        document_id: The document's own key.
        sign_off: The sign-off received in a review response.
    """
    store.put(sign_offs_namespace(firm_id, document_id), sign_off.id, sign_off.to_json())
