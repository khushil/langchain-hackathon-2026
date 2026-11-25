"""Read a run's request: the customer, the words of the request and the optional window."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from workflow.errors import InvalidRequestError

REQUIRED = ("user_id", "request")


def request_text(user_id: str, *, start: str | None = None, end: str | None = None) -> str:
    """Return the words of a request to assess a customer's transactions, built in this one place.

    The application and the notebook both ask with these words, so a recorded run answers either.

    Args:
        user_id: The customer, for example ``USR-001``.
        start: The first timestamp of the window, or None.
        end: The timestamp the window stops before, or None.

    Returns:
        ``Assess the transactions of <customer>``, with the window when there is one.
    """
    window = ""
    if start and end:
        window = f" from {start} up to {end}"
    elif start:
        window = f" from {start}"
    elif end:
        window = f" before {end}"
    return f"Assess the transactions of {user_id}{window}"


def check_request(request: Mapping[str, Any]) -> None:
    """Refuse a request that lacks a field a run needs.

    Args:
        request: The ``MonitorRequest``.

    Raises:
        InvalidRequestError: If the customer or the words of the request are missing; each is named.
    """
    missing = [name for name in REQUIRED if not request.get(name)]
    if missing:
        raise InvalidRequestError(f"The request lacks {', '.join(missing)}.")


def request_of(state: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the run's request from its state.

    Args:
        state: The graph state.

    Returns:
        The ``MonitorRequest`` with its optional ``start`` and ``end``.
    """
    return state["request"]
