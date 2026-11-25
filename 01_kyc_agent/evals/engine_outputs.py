"""Run the engine on the applications up to the review, and read each application's result.

The run stops where a person takes over: nothing here decides, answers or signs. The result of
each application is the plain JSON ``evals.evaluators`` reads, so the scoring never touches a
record or the engine.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from workflow.graph import build_graph
from workflow.reading import ModelSource
from workflow.requests import request_text


def _accounted(values: Mapping[str, Any]) -> dict[str, set[str]]:
    keys = {source_id: source["key"] for source_id, source in values["sources"].items()}
    accounted: dict[str, set[str]] = {}
    for source_id, record in values["accounting"].items():
        anchors = set(record["with_facts"]) | {u["anchor"] for u in record["without_facts"]}
        accounted[keys[source_id]] = anchors
    return accounted


def outputs_from_state(values: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Read each application's result from a run's state.

    Args:
        values: The state of a run that has reached the review interrupt.

    Returns:
        For each customer id, in application order: the proposed risk level and decision, whether
        the checks settled it, the name and date of birth the reading gave, and the counts of the
        application's units accounted for, as ``[accounted, expected]``.
    """
    proposals = {}
    for contents in values["facts"].values():
        fact = contents[0]
        if fact["kind"] == "proposal":
            proposals[fact["subject"]["anchor"].partition(":")[2]] = fact["attributes"]
    accounted = _accounted(values)
    anchors = [u["anchor"] for u in values["units"].values()]
    outputs = {}
    for customer_id in sorted(proposals):
        attributes = proposals[customer_id]
        applicant = values["applicants"][customer_id]
        pairs = [a for a in anchors if a.startswith(f"pair:{customer_id}/")]
        outputs[customer_id] = {
            "customer_id": customer_id,
            "risk_level": attributes["risk_level"],
            "decision": attributes["decision"],
            "settled": attributes["settled"],
            "profile": {
                "full_name": applicant["name"],
                "date_of_birth": applicant["date_of_birth"],
            },
            "accounting": {
                "applications": [int(f"row:{customer_id}" in accounted["applications"]), 1],
                "screenings": [sum(a in accounted["screenings"] for a in pairs), len(pairs)],
            },
        }
    return outputs


def run_engine(
    models: ModelSource, *, customer_ids: list[str] | None = None
) -> dict[str, dict[str, Any]]:
    """Run the engine on the applications to the review interrupt and read the results.

    Args:
        models: Gives the chat model for a role; ``get_model`` in production, a scripted reader in
            tests.
        customer_ids: The customers to read; every application when omitted.

    Returns:
        The result of each application, as ``outputs_from_state`` gives it.
    """
    graph = build_graph(models=models, checkpointer=InMemorySaver(), store=InMemoryStore())
    request: dict[str, Any] = {
        "request": request_text(None if customer_ids is None else len(customer_ids))
    }
    if customer_ids is not None:
        request["customer_ids"] = customer_ids
    config = {"configurable": {"thread_id": str(uuid.uuid4())}, "max_concurrency": 4}
    graph.invoke({"request": request}, config)
    return outputs_from_state(graph.get_state(config).values)
