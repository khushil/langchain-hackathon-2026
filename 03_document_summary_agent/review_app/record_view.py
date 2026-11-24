"""A finished brief read back from its run: its statements, the facts they cite and each source.

Nothing here lets anyone decide. A signed or returned brief is read, not edited, so its pages hold
the statements as they were written, the decision each fact stands on and the source paragraph or
table row each fact quotes.
"""

from __future__ import annotations

from dataclasses import dataclass

from fsi_common.records import Decision, Fact, SignOff
from review_app.context import RunInfo
from review_app.naming import Naming, RowField
from review_app.source_view import Segment, mark_quote, pick_decision
from utils.records import FACT_CONTEXT

NO_DECISION = "No decision"


def records_of(info: RunInfo, key: str) -> dict:
    """Return one collection of the run's state, or nothing when the state lacks it."""
    return info.state.get(key, {}) or {}


def decisions_by_subject(info: RunInfo) -> dict[str, Decision]:
    """Return the decision each fact or question of a finished brief stands on, one for each."""
    grouped: dict[str, list[Decision]] = {}
    for raw in records_of(info, "decisions").values():
        decision = Decision.model_validate(raw)
        grouped.setdefault(decision.subject_id, []).append(decision)
    held = info.state.get("sign_off")
    sign_off = SignOff.model_validate(held) if held else None
    return {sid: pick_decision(found, sign_off) for sid, found in grouped.items()}  # type: ignore[misc]


def cited_ids(info: RunInfo) -> list[str]:
    """Return the ids of the facts the finished brief cites, each once, in the brief's order."""
    brief = info.state.get("draft_brief") or {}
    cited = [fid for s in brief.get("statements", []) for fid in s["cites"]]
    return list(dict.fromkeys(cited))


def signed_facts(info: RunInfo) -> list[tuple[Fact, Decision | None]]:
    """Return the facts a finished brief cites, each with the decision it stands on."""
    decisions = decisions_by_subject(info)
    facts = records_of(info, "facts")
    return [
        (Fact.model_validate(facts[fid][0], context=FACT_CONTEXT), decisions.get(fid))
        for fid in cited_ids(info)
        if fid in facts
    ]


@dataclass(frozen=True)
class RecordFact:
    """A fact a statement cites: how it is named, where it opens and where its decision stands."""

    fact_id: str
    name: str
    decision: Decision | None


@dataclass(frozen=True)
class RecordStatement:
    """A statement of the finished brief with the facts it cites."""

    heading: str | None
    text: str
    facts: tuple[RecordFact, ...]


@dataclass(frozen=True)
class RecordPanel:
    """The source of one cited fact of a finished brief, ready to read."""

    fact: Fact
    place: str
    source_title: str
    digest: str
    unit_text: str
    segments: tuple[Segment, ...] | None
    row: tuple[RowField, ...] | None
    quote_found: bool
    decision: Decision | None


def record_statements(info: RunInfo, naming: Naming) -> tuple[RecordStatement, ...]:
    """Return the statements of a finished brief, each with the facts it cites.

    Args:
        info: The finished run.
        naming: The names of the firms and providers.

    Returns:
        The statements in the brief's order. A cited fact the run does not hold is left out.
    """
    held = {fact.id: (fact, decision) for fact, decision in signed_facts(info)}
    brief = info.state.get("draft_brief") or {}
    return tuple(
        RecordStatement(
            heading=statement.get("heading"),
            text=statement["text"],
            facts=tuple(
                RecordFact(fid, naming.fact_name(held[fid][0]), held[fid][1])
                for fid in statement["cites"]
                if fid in held
            ),
        )
        for statement in brief.get("statements", [])
    )


def _unit_text(info: RunInfo, fact: Fact) -> str:
    wanted = (fact.subject.source_id, fact.subject.anchor)
    for unit in records_of(info, "units").values():
        if (unit["source_id"], unit["anchor"]) == wanted:
            return records_of(info, "unit_text").get(unit["id"], "")
    return ""


def record_panel(info: RunInfo, naming: Naming, fact_id: str | None) -> RecordPanel | None:
    """Build the read-only source panel of a finished brief.

    Args:
        info: The finished run.
        naming: The names of the firms and providers.
        fact_id: The fact asked for in the address; the first cited fact when absent or unknown.

    Returns:
        The panel, or None when the brief cites no fact the run holds.
    """
    held = {fact.id: (fact, decision) for fact, decision in signed_facts(info)}
    if not held:
        return None
    fact, decision = held.get(fact_id or "") or next(iter(held.values()))
    text = _unit_text(info, fact)
    row = naming.row_fields(text, fact) if fact.subject.anchor.startswith("row:") else None
    segments = None if row is not None else mark_quote(text, fact.quote)
    source = records_of(info, "sources").get(fact.subject.source_id)
    return RecordPanel(
        fact=fact,
        place=naming.place(fact.subject.anchor),
        source_title=source["title"] if source else naming.place(fact.subject.anchor),
        digest=fact.provenance.as_of,
        unit_text=text,
        segments=segments,
        row=row,
        quote_found=(any(line.marked for f in row for line in f.lines))
        if row is not None
        else segments is not None,
        decision=decision,
    )
