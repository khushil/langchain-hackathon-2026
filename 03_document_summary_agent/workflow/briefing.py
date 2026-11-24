"""The brief step: statements written from facts that passed, each citing the facts it rests on."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from fsi_common.ids import digest_text
from fsi_common.records import Brief, Fact, Statement
from utils import PROJECT_ROOT
from utils.models import ROLE_MODELS
from workflow.checks import run_check
from workflow.closing import all_facts
from workflow.engine_state import EngineState
from workflow.errors import BriefCitationError, BriefDraftError
from workflow.requests import request_of
from workflow.sections import ModelSource

BRIEF_INSTRUCTIONS = (PROJECT_ROOT / "workflow" / "brief_instructions.md").read_text(
    encoding="utf-8"
)
BRIEF_PROMPT_VERSION = f"brief-{digest_text(BRIEF_INSTRUCTIONS)[7:15]}"
CITABLE_KINDS = ("obligation", "firm_attribute", "provider_attribute")
"""The kinds of fact the brief may cite: the obligations and what the tables say of the firm."""


class DraftStatement(BaseModel):
    """One statement as the model writes it, before it becomes a record."""

    heading: str | None = Field(default=None, description="The part of the brief it sits under")
    text: str = Field(description="The statement")
    cites: list[str] = Field(description="The ids of the facts it rests on, copied unchanged")


class BriefDraft(BaseModel):
    """The model's reply: the statements of the brief, in order."""

    statements: list[DraftStatement] = Field(description="The brief's statements")


def citable_facts(state: EngineState) -> dict[str, Fact]:
    """Return the facts the brief may cite: one content, every check passed, a citable kind.

    Args:
        state: The graph state.

    Returns:
        The facts by id.
    """
    held = state.get("facts", {})
    return {
        fact.id: fact
        for fact in all_facts(state)
        if len(held[fact.id]) == 1 and fact.passed_checks and fact.kind in CITABLE_KINDS
    }


def fact_line(fact: Fact) -> str:
    """Return the line that gives a fact to the brief's model.

    Args:
        fact: The fact.

    Returns:
        ``<id> | <kind> | <anchor> | ...`` with the requirements (joined by semicolons when a
        fact holds more than one), the deadline and the quote.
    """
    parts = [fact.id, fact.kind, fact.subject.anchor]
    if fact.kind == "obligation":
        requirements = fact.attributes.get("requirement")
        shown = "; ".join(requirements) if isinstance(requirements, list) else requirements
        parts.append(f"requirement: {shown}")
        parts.append(f"deadline: {fact.attributes.get('deadline') or 'none'}")
    else:
        parts.append(f"value: {fact.attributes}")
    parts.append(f'quote: "{fact.quote}"')
    return " | ".join(parts)


def brief_task(request: str, facts: dict[str, Fact]) -> str:
    """Return the task text the brief's model is given.

    Args:
        request: The request the brief answers.
        facts: The facts it may cite, by id.

    Returns:
        The request and one line for each fact.
    """
    lines = "\n".join(fact_line(fact) for fact in facts.values())
    return f"Request: {request}\n\nFacts:\n{lines}"


def check_citations(draft: BriefDraft, facts: dict[str, Fact], state: EngineState) -> None:
    """Refuse a draft with no statement, or with a statement that cites a fact it may not.

    Args:
        draft: The model's statements.
        facts: The facts the brief may cite.
        state: The graph state, to say why a cited id is not citable.

    Raises:
        BriefDraftError: If the draft has no statement or a statement cites no fact.
        BriefCitationError: If a statement cites an id that is not a fact that passed; every such
            id is named, with the reason.
    """
    if not draft.statements:
        raise BriefDraftError("The model wrote a brief with no statement.")
    held = state.get("facts", {})
    problems: dict[str, str] = {}
    for number, statement in enumerate(draft.statements, 1):
        if not statement.cites:
            raise BriefDraftError(f"Statement {number} of the brief cites no fact.")
        for fact_id in statement.cites:
            if fact_id in facts:
                continue
            if fact_id not in held:
                problems[fact_id] = "is not a fact of this run"
            elif len(held[fact_id]) > 1:
                problems[fact_id] = "has two readings that differ, so it is not cited"
            else:
                problems[fact_id] = "did not pass its checks or is not a kind the brief cites"
    if problems:
        shown = "; ".join(f"{fact_id} {why}" for fact_id, why in sorted(problems.items()))
        raise BriefCitationError(
            f"The brief cites fact(s) it may not: {shown}.", fact_ids=sorted(problems)
        )


def build_statements(draft: BriefDraft) -> list[Statement]:
    """Turn the model's statements into records, each citing its facts once.

    Args:
        draft: The model's statements, already checked.

    Returns:
        The statement records, in order.

    Raises:
        BriefDraftError: If a statement is blank; the statement's number is named.
    """
    statements = []
    for number, drafted in enumerate(draft.statements, 1):
        cites = list(dict.fromkeys(drafted.cites))
        try:
            statements.append(
                Statement.build(heading=drafted.heading or None, text=drafted.text, cites=cites)
            )
        except ValidationError as exc:
            raise BriefDraftError(f"Statement {number} of the brief is not valid: {exc}") from exc
    return statements


def make_brief_step(models: ModelSource) -> Callable[[EngineState], dict[str, Any]]:
    """Build the brief step, which writes the brief with the model ``models`` gives.

    Args:
        models: Gives the chat model for a role.

    Returns:
        The graph node that writes the brief.
    """

    def brief_step(state: EngineState) -> dict[str, Any]:
        request = request_of(state)
        facts = citable_facts(state)
        chat = models("brief").with_structured_output(BriefDraft)
        reply = chat.invoke(
            [
                SystemMessage(BRIEF_INSTRUCTIONS),
                HumanMessage(brief_task(request["request"], facts)),
            ]
        )
        try:
            draft = reply if isinstance(reply, BriefDraft) else BriefDraft.model_validate(reply)
        except ValidationError as exc:
            raise BriefDraftError(f"The model's reply is not a brief: {exc}") from exc
        check_citations(draft, facts, state)
        statements = build_statements(draft)
        brief = Brief.build(
            request=request["request"],
            sources=sorted(state["sources"]),
            statements=statements,
            open_question_ids=sorted(state.get("open_questions", {})),
            model=ROLE_MODELS["brief"].model,
            prompt_version=BRIEF_PROMPT_VERSION,
        )
        cited = {fact_id for statement in statements for fact_id in statement.cites}
        obligations = sorted(i for i, f in facts.items() if f.kind == "obligation")
        uncovered = [i for i in obligations if i not in cited]
        checks = {
            **run_check(
                "brief-cites-passed.v1",
                brief.id,
                passed=True,
                detail=f"{len(statements)} statements cite {len(cited)} of {len(facts)} facts that "
                "passed; every cited fact is one that passed",
            ),
            **run_check(
                "brief-covers-obligations.v1",
                brief.id,
                passed=not uncovered,
                detail=f"{len(obligations) - len(uncovered)} of {len(obligations)} obligation "
                "facts that passed are cited"
                + (f"; not cited: {', '.join(uncovered)}" if uncovered else ""),
            ),
        }
        return {"draft_brief": brief.to_json(), "check_results": checks}

    return brief_step
