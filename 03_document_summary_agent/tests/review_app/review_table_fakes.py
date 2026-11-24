"""A review whose brief cites paragraphs and facts read from the firm and provider tables."""

from __future__ import annotations

from review_fakes import Review, _state, cite, section_seven_review

from context.tables import read_tables
from fsi_common.examples.data import build_examples
from fsi_common.records import Brief, Fact, Statement
from utils.state import ReviewRequest, ReviewStatement

FIRM_ROW = "row:FIRM-001"
FIRST_PROVIDER = "row:PROVIDER-001"
SECOND_PROVIDER = "row:PROVIDER-002"


def table_fact(facts: list[Fact], anchor: str, field: str, provider: str | None = None) -> Fact:
    """Return the fact of a table row for one field, or for the link to one provider."""
    for fact in facts:
        held = fact.attributes
        if fact.subject.anchor != anchor or held.get("field") != field:
            continue
        if provider is None or held.get("provider_id") == provider:
            return fact
    raise LookupError(f"No fact for {anchor} {field} {provider}")


def tables_review() -> Review:
    """Build a review of one paragraph and the firm and provider facts a brief cites about them.

    The statements are written in words, as the brief writer is told to write them.
    """
    base = section_seven_review()
    paragraph = next(iter(base.facts.values()))
    tables = read_tables("FIRM-001")
    rows = list(tables.facts)
    chosen = {
        "assets": table_fact(rows, FIRM_ROW, "total_assets"),
        "manager": table_fact(rows, FIRM_ROW, "operational_resilience_senior_manager"),
        "link": table_fact(rows, FIRM_ROW, "provider_link", provider="PROVIDER-001"),
        "name": table_fact(rows, FIRST_PROVIDER, "name"),
        "service": table_fact(rows, SECOND_PROVIDER, "service"),
    }
    plan = [
        ("Firm profile", "Harbour Mutual Bank has total assets of £9 billion.", ["assets"]),
        (
            "Firm profile",
            "Harbour Mutual Bank has not named a senior manager for operational resilience.",
            ["manager"],
        ),
        (
            "Third-party providers",
            "NimbusCloud hosts the bank's core banking under a contract that ends on 30 June 2027.",
            ["link", "name"],
        ),
        ("Third-party providers", "PayCore Ltd processes the bank's card payments.", ["service"]),
    ]
    statements = [
        Statement.build(heading=h, text=t, cites=[chosen[k].id for k in keys])
        for h, t, keys in plan
    ]
    statements.append(
        Statement.build(
            heading="Incident reporting", text="Notify the regulator.", cites=[paragraph.id]
        )
    )
    facts = [*chosen.values(), paragraph]
    by_id = {f.id: f for f in facts}
    texts = {u.anchor: tables.unit_text[u.id] for u in tables.units}
    brief = Brief.build(
        request="Summarise document PS26-4 for FIRM-001",
        sources=sorted({f.subject.source_id for f in facts}),
        statements=statements,
        open_question_ids=[],
        model="claude-opus-5-5",
        prompt_version="1",
    )
    review_statements = [
        ReviewStatement(
            statement_id=s.id,
            heading=s.heading,
            text=s.text,
            facts=[cite(by_id[i], text=texts.get(by_id[i].subject.anchor)) for i in s.cites],
        )
        for s in brief.statements
    ]
    request = ReviewRequest(
        brief_id=brief.id,
        brief_digest=brief.content_digest,
        request=brief.request,
        statements=review_statements,
        open_questions=[],
    )
    state = _state([build_examples().document, *tables.sources], facts, brief, None)
    return Review(request, state, by_id, None, brief)
