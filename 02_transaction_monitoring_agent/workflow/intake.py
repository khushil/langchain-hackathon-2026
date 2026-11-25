"""The first step: read the customer's stream and profile into sources, units and facts."""

from __future__ import annotations

from typing import Any

from context.facts import customer_facts
from context.reader import StreamRead, read_stream
from workflow.checks import run_check
from workflow.requests import check_request, request_of
from workflow.state import MonitorState


def stream_of(state: MonitorState) -> StreamRead:
    """Read again the stream the run's request asks for; two reads give identical records.

    Args:
        state: The graph state, holding the request.

    Returns:
        The stream as the data files give it now.

    Raises:
        InvalidRequestError: If the request lacks a field.
        CustomerNotFoundError: If the customer is not in the profile table.
        EmptyStreamError: If the customer has no transaction in the window.
    """
    request = request_of(state)
    check_request(request)
    return read_stream(request["user_id"], start=request.get("start"), end=request.get("end"))


def read_sources(state: MonitorState) -> dict[str, Any]:
    """Read the customer's transactions in the window and the customer's profile.

    Args:
        state: The graph state, holding the request.

    Returns:
        The state update: sources, units, unit texts, the profile's facts and the counts read.
    """
    stream = stream_of(state)
    facts = customer_facts(stream)
    transactions, profiles = stream.sources
    count = len(stream.transactions)
    checks = {
        **run_check(
            "units-read.v1",
            transactions.id,
            passed=True,
            detail=f"{count} of {count} transactions of {stream.user_id} in the window read",
        ),
        **run_check(
            "units-read.v1",
            profiles.id,
            passed=True,
            detail=f"1 of 1 profile rows of {stream.user_id} read as a unit",
        ),
    }
    return {
        "sources": {s.id: s.to_json() for s in stream.sources},
        "units": {u.id: u.to_json() for u in stream.units},
        "unit_text": stream.unit_text,
        "facts": {f.id: f.to_json() for f in facts},
        "check_results": checks,
    }
