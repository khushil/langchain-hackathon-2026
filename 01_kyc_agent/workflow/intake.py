"""The first step: read the applications and every pairing, and send each application on."""

from __future__ import annotations

from typing import Any

from langgraph.types import Send

from context.errors import AccountingError
from context.reader import entries_of, read_applications, read_screenings
from utils.records import customer_of_anchor
from workflow.checks import run_check
from workflow.engine_state import EngineState
from workflow.requests import chosen_customers, request_of


def read_sources(state: EngineState) -> dict[str, Any]:
    """Read the chosen applications and each one set against each list entry into units.

    Args:
        state: The graph state, holding the request.

    Returns:
        The state update: both sources, a unit for each application and each pair, their texts and
        the counts read.

    Raises:
        ApplicationNotFoundError: If a customer the request names has no application.
        InvalidRequestError: If the request holds an empty list of customers.
    """
    customers = chosen_customers(request_of(state))
    applications = read_applications(customers)
    screenings = read_screenings(customers)
    entries = entries_of()
    expected = len(applications.units) * len(entries)
    if len(screenings.units) != expected:
        raise AccountingError(
            f"{len(screenings.units)} screenings were read, and {len(applications.units)} "
            f"applications by {len(entries)} list entries make {expected}."
        )
    checks = {
        **run_check(
            "units-read.v1",
            applications.source.id,
            passed=True,
            detail=f"{len(applications.units)} of {len(applications.units)} applications "
            "read as units",
        ),
        **run_check(
            "units-read.v1",
            screenings.source.id,
            passed=True,
            detail=f"{len(screenings.units)} screenings read as units: "
            f"{len(applications.units)} applications by {len(entries)} list entries",
        ),
    }
    return {
        "sources": {s.id: s.to_json() for s in (applications.source, screenings.source)},
        "units": {u.id: u.to_json() for u in (*applications.units, *screenings.units)},
        "unit_text": {**applications.unit_text, **screenings.unit_text},
        "check_results": checks,
    }


def send_applications(state: EngineState) -> list[Send]:
    """Send one read for each application the run holds, in application order.

    Args:
        state: The graph state, whose units name the applications.

    Returns:
        One ``Send`` to the read step for each application.
    """
    request = request_of(state)
    customers = [
        customer_of_anchor(unit["anchor"])
        for unit in state["units"].values()
        if unit["anchor"].startswith("row:")
    ]
    return [
        Send("read_application", {"request": dict(request), "customer_id": customer})
        for customer in sorted(customers)
    ]
