"""The brief step: one statement for each application, written by code from facts that passed."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from context.reader import read_applications
from fsi_common.records import Brief, Fact, Statement
from utils.records import APPLICANT_KINDS, customer_of_anchor
from workflow.checks import run_check
from workflow.closing import all_facts
from workflow.engine_state import EngineState
from workflow.errors import BriefDraftError
from workflow.requests import chosen_customers, request_of

BRIEF_MODEL = "code"
BRIEF_PROMPT_VERSION = "statements-1"
"""No model writes a statement: each is made from the proposal's own words by code."""


def statement_text(customer_id: str, name: str | None, proposal: Fact) -> str:
    """Return the statement for one application, in the proposal's own words.

    Args:
        customer_id: The customer.
        name: The applicant's name, or None when it was not established.
        proposal: The application's proposal fact.

    Returns:
        A sentence that states the proposed level and decision, and whether the checks settled it.
    """
    attributes = proposal.attributes
    who = f"{name} ({customer_id})" if name else f"The applicant {customer_id}"
    head = f"{who}: proposed {attributes['risk_level']} risk and {attributes['decision']}."
    if attributes["settled"]:
        return f"{head} Settled by the checks. {attributes['basis']}"
    return f"{head} {attributes['basis']}"


def write_brief(state: EngineState) -> dict[str, Any]:
    """Write the statements the reviewer reads and signs, each citing the facts it rests on.

    Args:
        state: The graph state after the counts have closed.

    Returns:
        The state update: the draft brief and the checks on it.

    Raises:
        BriefDraftError: If an application has no proposal or a statement cannot be built.
    """
    request = request_of(state)
    applications = read_applications(chosen_customers(request))
    held = state["facts"]
    by_customer: dict[str, list[Fact]] = {}
    for fact in all_facts(state):
        if len(held[fact.id]) == 1 and fact.passed_checks:
            by_customer.setdefault(customer_of_anchor(fact.subject.anchor), []).append(fact)
    statements = []
    for unit in applications.units:
        customer = customer_of_anchor(unit.anchor)
        facts = by_customer.get(customer, [])
        proposal = next((f for f in facts if f.kind == "proposal"), None)
        if proposal is None:
            raise BriefDraftError(f"The application {customer} has no proposal that passed.")
        name = next((f.attributes["value"] for f in facts if f.kind == "applicant_name"), None)
        evidence = [f for f in facts if f.kind in (*APPLICANT_KINDS, "screening")]
        try:
            statements.append(
                Statement.build(
                    heading=f"{customer} {name}" if name else customer,
                    text=statement_text(customer, name, proposal),
                    cites=[proposal.id, *[f.id for f in evidence]],
                )
            )
        except ValidationError as exc:
            raise BriefDraftError(f"The statement for {customer} is not valid: {exc}") from exc
    brief = Brief.build(
        request=request["request"],
        sources=sorted(state["sources"]),
        statements=statements,
        open_question_ids=sorted(state.get("open_questions", {})),
        model=BRIEF_MODEL,
        prompt_version=BRIEF_PROMPT_VERSION,
    )
    cited = {fact_id for s in statements for fact_id in s.cites}
    checks = {
        **run_check(
            "brief-cites-passed.v1",
            brief.id,
            passed=all(f.passed_checks for f in all_facts(state) if f.id in cited),
            detail=f"{len(statements)} statements cite {len(cited)} facts, each one that passed "
            "its checks",
        ),
        **run_check(
            "brief-covers-applications.v1",
            brief.id,
            passed=len(statements) == len(applications.units),
            detail=f"{len(statements)} of {len(applications.units)} applications have a statement",
        ),
    }
    return {"draft_brief": brief.to_json(), "check_results": checks}
