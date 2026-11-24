"""Scripted chat models and review responses for the workflow's tests; no test makes a live call."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from typing import Any

from context.reader import SectionRead, read_document
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableLambda
from workflow.briefing import BriefDraft, DraftStatement

from fsi_common.examples.data import REVIEWER
from fsi_common.records import Decision, SignOff
from sub_agent import Obligation, SectionSummary
from utils.state import ReviewRequest, ReviewResponse

DOCUMENT = read_document("PS26-4")
DEADLINE = re.compile(r"within \d+ (?:business )?(?:hours|days)|by \d{1,2} \w+ \d{4}")
FACT_LINE = re.compile(r"^(fact:[0-9a-f]{16}) \| (\w+) \| (\S+) \|", re.MULTILINE)
REVIEW_DATE = "2026-11-25"


def default_summary(section: SectionRead) -> SectionSummary:
    """Read a section as a careful model would: one obligation for each 'must' paragraph."""
    obligations = []
    for paragraph in section.paragraphs:
        if " must " not in paragraph.text:
            continue
        found = DEADLINE.search(paragraph.text)
        obligations.append(
            Obligation(
                requirement=f"Duty from paragraph {paragraph.number}",
                paragraph=paragraph.number,
                deadline=found.group(0) if found else None,
                evidence=" ".join(paragraph.text.split()[:12]),
            )
        )
    return SectionSummary(
        number=section.number,
        title=section.title,
        summary=f"Section {section.number} sets {len(obligations)} duties.",
        obligations=obligations,
    )


def ghost_summary(section: SectionRead) -> SectionSummary:
    """Read a section as a model that also cites a paragraph the section does not have."""
    base = default_summary(section)
    if not base.obligations:
        return base
    extra = base.obligations[0].model_copy(update={"paragraph": f"{section.number}.99"})
    return base.model_copy(update={"obligations": [*base.obligations, extra]})


def bundle_records(values: dict[str, Any]) -> list[Any]:
    """Return a run's state as the records the contract's bundle check reads."""
    from fsi_common.records import RECORD_TYPES, Fact
    from utils.records import FACT_CONTEXT

    records = []
    for key in ("sources", "units", "accounting", "open_questions", "disagreements", "decisions"):
        for data in values.get(key, {}).values():
            records.append(RECORD_TYPES[data["schema"]].model_validate(data, context=FACT_CONTEXT))
    for contents in values["facts"].values():
        for data in contents:
            records.append(Fact.model_validate(data, context=FACT_CONTEXT))
    for key in ("draft_brief", "sign_off"):
        if values.get(key):
            records.append(RECORD_TYPES[values[key]["schema"]].model_validate(values[key]))
    return records


def default_brief(task: str) -> BriefDraft:
    """Write one statement for each section's obligations and one for the firm's profile."""
    by_section: dict[str, list[str]] = {}
    firm: list[str] = []
    for fact_id, kind, anchor in FACT_LINE.findall(task):
        if kind == "obligation":
            by_section.setdefault(anchor.partition(":")[2].partition(".")[0], []).append(fact_id)
        elif kind == "firm_attribute" and len(firm) < 2:
            firm.append(fact_id)
    statements = [
        DraftStatement(
            heading=f"Section {number}",
            text=f"The firm has {len(ids)} duties under section {number}.",
            cites=ids,
        )
        for number, ids in sorted(by_section.items(), key=lambda item: int(item[0]))
    ]
    if firm:
        statements.append(
            DraftStatement(heading="The firm", text="The firm's profile applies.", cites=firm)
        )
    return BriefDraft(statements=statements)


class ScriptedModels:
    """Gives a fake chat model for each role, and keeps what it was asked and how many at once."""

    def __init__(
        self,
        *,
        section: Callable[[SectionRead], SectionSummary] = default_summary,
        brief: Callable[[str], BriefDraft] = default_brief,
        delay: float = 0.0,
        fail_sections: tuple[str, ...] = (),
    ) -> None:
        self.section, self.brief, self.delay = section, brief, delay
        self.fail_sections = fail_sections
        self.calls: list[tuple[str, str]] = []
        self.current = self.peak = 0
        self._lock = threading.Lock()

    def __call__(self, role: str) -> BaseChatModel:
        return FakeRoleModel(role=role, owner=self)

    def _answer(self, role: str, messages: list[Any]) -> Any:
        text = messages[-1].content
        with self._lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
            self.calls.append((role, text.partition("\n")[0]))
        try:
            if self.delay:
                time.sleep(self.delay)
            if role == "section":
                number = re.search(r"^Number: (\S+)", text, re.MULTILINE).group(1)
                if number in self.fail_sections:
                    raise RuntimeError(f"the model call for section {number} failed")
                return self.section(DOCUMENT.section(number))
            return self.brief(text)
        finally:
            with self._lock:
                self.current -= 1


class FakeRoleModel(BaseChatModel):
    """A chat model whose structured output is whatever its owner scripts for the role."""

    role: str
    owner: Any

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise AssertionError("the workflow asks for structured output only")

    def with_structured_output(self, schema, **kwargs):
        return RunnableLambda(lambda messages: self.owner._answer(self.role, list(messages)))


def respond(
    request: ReviewRequest,
    *,
    outcome: str = "signed",
    reviewer: dict[str, str] = REVIEWER,
    decide: str | None = "accept",
    reason: str = "Returned for a rewrite.",
) -> ReviewResponse:
    """Answer a review request as a named person would: decide on each fact, then sign or return."""
    decisions = []
    if decide:
        for statement in request.statements:
            for cited in statement.facts:
                if cited.carry.outcome != "carried":
                    decisions.append(
                        Decision.on(
                            cited.fact,
                            outcome=decide,
                            reason="Checked against the paragraph.",
                            reviewer=reviewer,
                            date=REVIEW_DATE,
                            amendment="Reworded." if decide == "amend" else None,
                        )
                    )
    sign_off = SignOff.build(
        brief_id=request.brief_id,
        brief_digest=request.brief_digest,
        reviewer=reviewer,
        date=REVIEW_DATE,
        outcome=outcome,
        assumptions=[],
        reason=reason if outcome == "returned" else None,
    )
    return ReviewResponse(reviewer=reviewer, decisions=decisions, sign_off=sign_off)


def request_for(*sections: str) -> dict[str, Any]:
    """Return a run's input for PS26-4 and FIRM-001, filtered to sections when any are named."""
    request: dict[str, Any] = {
        "document_id": "PS26-4",
        "firm_id": "FIRM-001",
        "request": "Summarise document PS26-4 for FIRM-001",
    }
    if sections:
        request["sections"] = list(sections)
    return {"request": request}


class Harness:
    """A compiled graph with its own checkpointer and store, and the calls a test makes on it."""

    def __init__(self, models: ScriptedModels | None = None, *, store: Any = None) -> None:
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore
        from workflow.graph import build_graph

        self.models = models or ScriptedModels()
        self.store = store or InMemoryStore()
        self.graph = build_graph(models=self.models, checkpointer=InMemorySaver(), store=self.store)
        self.count = 0

    def start(self, *sections: str, thread: str | None = None) -> dict[str, Any]:
        """Run to the review interrupt, and return the thread's configuration."""
        self.count += 1
        config = {
            "configurable": {"thread_id": thread or f"thread-{self.count}"},
            "max_concurrency": 4,
        }
        self.graph.invoke(request_for(*sections), config)
        return config

    def values(self, config: dict[str, Any]) -> dict[str, Any]:
        """Return the thread's state as it stands."""
        return self.graph.get_state(config).values

    def review_request(self, config: dict[str, Any]) -> ReviewRequest:
        """Return the payload the review interrupt holds."""
        from utils.records import FACT_CONTEXT

        task = self.graph.get_state(config).tasks[0]
        return ReviewRequest.model_validate(task.interrupts[0].value, context=FACT_CONTEXT)

    def resume(self, config: dict[str, Any], response: ReviewResponse) -> dict[str, Any]:
        """Resume the review with a response, and return the graph's output."""
        from langgraph.types import Command

        return self.graph.invoke(
            Command(resume=response.model_dump(mode="json", by_alias=True)), config
        )
