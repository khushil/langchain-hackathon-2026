"""Read a run's request: the words, and the optional list of customers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from workflow.errors import InvalidRequestError


def request_text(count: int | None = None) -> str:
    """Return the words of a request, built in this one place.

    The application and the notebook both ask with these words, so a recorded run answers either.

    Args:
        count: The number of applications asked for, or None for every application.

    Returns:
        The request.
    """
    if count is None:
        return "Review the proposed decisions on every application"
    return f"Review the proposed decisions on {count} application{'s' if count != 1 else ''}"


def request_of(state: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the run's request from its state.

    Args:
        state: The graph state.

    Returns:
        The request, with its optional ``customer_ids`` key.
    """
    return state["request"]


def chosen_customers(request: Mapping[str, Any]) -> list[str] | None:
    """Return the customers a request names.

    Args:
        request: The run's request.

    Returns:
        The customer ids, or None when the request leaves them out, which reads every application.

    Raises:
        InvalidRequestError: If the request holds an empty list; leave the key out to read all.
    """
    wanted = request.get("customer_ids")
    if wanted is None:
        return None
    if not wanted:
        raise InvalidRequestError(
            "The request holds an empty list of customers; "
            "leave 'customer_ids' out to read them all."
        )
    return list(dict.fromkeys(wanted))
