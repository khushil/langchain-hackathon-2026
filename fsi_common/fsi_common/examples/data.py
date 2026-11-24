"""The valid example records, built from the starter's fictional policy statement and firm tables.

The sources' digests and the unit texts are those of the starter's files as carried into topic 03.
The reviewer, her decisions and her answer are invented for the examples.
"""

from __future__ import annotations

from dataclasses import dataclass

from fsi_common.ids import digest_text
from fsi_common.records import (
    Brief,
    Decision,
    Disagreement,
    Fact,
    OpenQuestion,
    SignOff,
    Source,
    SourceUnit,
    Statement,
    UnitAccounting,
    fact_topic_context,
    judged_digest,
)

FACT_KINDS = (
    "obligation",
    "permission",
    "guidance",
    "definition",
    "scope",
    "effective_date",
    "regulator_action",
    "context",
    "firm_attribute",
    "provider_attribute",
)
"""The closed list the examples are validated with (topic 03's list)."""

COPIED_ATTRIBUTES = ("deadline",)
"""The attributes copied word for word from the source, which enter a fact's id (topic 03's)."""

FACT_CONTEXT = fact_topic_context(kinds=FACT_KINDS, copied_attributes=COPIED_ATTRIBUTES)
STARTER = "github.com/langchain-samples/fsi-hackathon-london-2026"
TERMS = f"Fictional sample data from the FSI hackathon starter ({STARTER}), carried with credit"
REVIEWER = {"name": "Dana Whitfield", "role": "Head of Compliance"}
REVIEW_DATE = "2026-11-25"

PARA_7_1 = (
    "7.1 Firms must submit an initial notification to the FSOA within 4 hours of classifying an "
    "incident as a major incident, and in any case no later than 24 hours after the incident is "
    "first detected."
)
PARA_9_3 = (
    "9.3 For all firms, contracts with material third-party providers that were in place before "
    "1 January 2027 must be updated to meet paragraph 6.3 at their next renewal, or by 31 December "
    "2028, whichever is earlier."
)
FIRM_001_ROW = (
    '{"firm_id": "FIRM-001", "name": "Harbour Mutual Bank", "type": "retail bank", "customers": '
    '1200000, "total_assets": "£9 billion", "operational_resilience_senior_manager": null, '
    '"notes": '
    '"Mobile banking and card payments both run on NimbusCloud.", "providers": [ { "provider_id": '
    '"PROVIDER-001", "contract_end": "30 June 2027", "material": true }, { "provider_id": '
    '"PROVIDER-002", "contract_end": "31 December 2029", "material": true }]}'
)
PROVIDER_002_ROW = (
    '{"provider_id": "PROVIDER-002", "name": "PayCore Ltd", "service": "card processing"}'
)

PARAGRAPHS_PER_SECTION = (5, 5, 5, 5, 5, 6, 5, 5, 4, 3)
"""PS26-4 has 10 sections and 48 numbered paragraphs."""


@dataclass(frozen=True)
class Examples:
    """Every valid example record, by name."""

    document: Source
    firms: Source
    providers: Source
    unit_7_1: SourceUnit
    unit_9_3: SourceUnit
    unit_firm: SourceUnit
    unit_provider: SourceUnit
    fact_7_1: Fact
    fact_9_3: Fact
    fact_notes: Fact
    fact_service: Fact
    fact_small_firm: Fact
    fact_7_1_rerun: Fact
    fact_7_1_variant: Fact
    question: OpenQuestion
    disagreement: Disagreement
    variant_disagreement: Disagreement
    accept_7_1: Decision
    answer: Decision
    brief: Brief
    sign_off: SignOff
    document_accounting: UnitAccounting
    firms_accounting: UnitAccounting


def _source(key: str, title: str, kind: str, digest: str, locator: str) -> Source:
    return Source.build(
        key=key, title=title, kind=kind, digest=digest, locator=locator, terms=TERMS
    )


def _unit(source: Source, anchor: str, text: str) -> SourceUnit:
    return SourceUnit.build(source_id=source.id, anchor=anchor, text_digest=digest_text(text))


def _provenance(
    source: Source, anchor: str, *, by_model: bool, version: str = "0.1.0", prompt: str = "1"
) -> dict[str, object]:
    if by_model:
        extractor = {"name": "section-reader", "version": version}
        return {
            "source_id": source.id,
            "anchor": anchor,
            "extractor": extractor,
            "model": "claude-sonnet-5-5",
            "prompt_version": prompt,
            "as_of": source.digest,
        }
    extractor = {"name": "table-reader", "version": "0.1.0"}
    return {
        "source_id": source.id,
        "anchor": anchor,
        "extractor": extractor,
        "as_of": source.digest,
    }


def _checks(*names: str, detail: str = "found word for word in the unit's text") -> list[dict]:
    return [{"check": name, "outcome": "pass", "detail": detail} for name in names]


def _fact(
    source: Source, anchor: str, kind: str, quote: str, attributes: dict, **extra: object
) -> Fact:
    by_model = kind not in {"firm_attribute", "provider_attribute"}
    return Fact.build(
        context=FACT_CONTEXT,
        kind=kind,
        subject={"source_id": source.id, "anchor": anchor},
        quote=quote,
        attributes=attributes,
        status=extra.get("status", {"status": "documented"}),
        provenance=extra.get("provenance", _provenance(source, anchor, by_model=by_model)),
        checks=extra.get("checks", _checks("quote-verbatim.v1")),
    )


def _claim(fact: Fact) -> dict[str, str]:
    return {"fact_id": fact.id, "judged_digest": judged_digest(fact)}


def paragraph_anchors() -> list[str]:
    """Return the anchors of PS26-4's 48 paragraphs, in document order.

    Returns:
        ``para:1.1`` to ``para:10.3``.
    """
    return [
        f"para:{s}.{p}"
        for s, count in enumerate(PARAGRAPHS_PER_SECTION, 1)
        for p in range(1, count + 1)
    ]


def build_examples() -> Examples:
    """Build every valid example record.

    Returns:
        The examples, each with its content-derived id.
    """
    data = "03_document_summary_agent/data"
    document = _source(
        "PS26-4",
        "Policy Statement PS26/4: Operational resilience and third-party technology risk",
        "document",
        "sha256:48e71bd7b38e8d7dcd8c5bfcfca55c0bb8d1be0a902aaea8423df52be08440a3",
        f"{data}/documents/PS26-4.md",
    )
    firms = _source(
        "firms",
        "Firm profiles",
        "table",
        "sha256:f11d80dbdedcdd2f4fbcc8ad602692d5849887fd68a8a18aeb0a27dd29935750",
        f"{data}/firms.jsonl",
    )
    providers = _source(
        "third_party_providers",
        "Third-party providers",
        "table",
        "sha256:ef799080725fbe3a10238261de27ce377b00bfd1b92e25e18bb55b13aad30cea",
        f"{data}/third_party_providers.jsonl",
    )
    deadline_7_1 = PARA_7_1.split("FSOA ", 1)[1].removesuffix(".")
    quote_7_1 = (
        "Firms must submit an initial notification to the FSOA within 4 hours of classifying an "
        "incident as a major incident"
    )
    attributes_7_1 = {
        "requirement": "Notify the regulator of a major incident",
        "actor": "firm",
        "deadline": deadline_7_1,
    }
    fact_7_1 = _fact(
        document,
        "para:7.1",
        "obligation",
        quote_7_1,
        attributes_7_1,
        checks=_checks("quote-verbatim.v1", "deadline-verbatim.v1"),
    )
    fact_7_1_rerun = _fact(
        document,
        "para:7.1",
        "obligation",
        quote_7_1,
        attributes_7_1,
        provenance=_provenance(document, "para:7.1", by_model=True, version="0.2.0", prompt="2"),
        checks=_checks(
            "quote-verbatim.v1", "deadline-verbatim.v1", detail="matched against paragraph 7.1"
        ),
    )
    fact_7_1_variant = _fact(
        document,
        "para:7.1",
        "obligation",
        quote_7_1,
        attributes_7_1 | {"requirement": "Tell the FSOA about a major incident"},
        checks=_checks("quote-verbatim.v1", "deadline-verbatim.v1"),
    )
    fact_9_3 = _fact(
        document,
        "para:9.3",
        "obligation",
        "must be updated to meet paragraph 6.3 at their next renewal, or by 31 December 2028, "
        "whichever is earlier",
        {
            "requirement": "Update contracts with material third-party providers made before "
            "1 January 2027 to meet paragraph 6.3",
            "actor": "firm",
            "deadline": "at their next renewal, or by 31 December 2028, whichever is earlier",
            "cross_refs": ["6.3"],
        },
        checks=_checks("quote-verbatim.v1", "deadline-verbatim.v1"),
    )
    fact_notes = _fact(
        firms,
        "row:FIRM-001",
        "firm_attribute",
        "Mobile banking and card payments both run on NimbusCloud.",
        {"field": "notes"},
    )
    fact_service = _fact(
        providers,
        "row:PROVIDER-002",
        "provider_attribute",
        '"service": "card processing"',
        {"field": "service", "value": "card processing"},
    )
    small_firm_rule = {
        "id": "small-firm-thresholds",
        "version": "1",
        "statement": "Paragraph 2.3: a small firm has fewer than 250,000 customers and total "
        "assets of less than £5 billion; 1,200,000 customers exceeds the first threshold",
        "match_rate": {"matched": 1, "population": 1},
    }
    fact_small_firm = _fact(
        firms,
        "row:FIRM-001",
        "firm_attribute",
        '"customers": 1200000',
        {"field": "customers", "small_firm": False},
        status={"status": "inferred", "rule": small_firm_rule},
    )
    unit_firm = _unit(firms, "row:FIRM-001", FIRM_001_ROW)
    question = OpenQuestion.build(
        about={"source_id": firms.id, "anchor": "row:FIRM-001"},
        question="Were the firm's contracts with NimbusCloud and PayCore Ltd in place before "
        "1 January 2027, and when does each next renew?",
        why_unknown="The firm table gives each contract's end date (30 June 2027 and "
        "31 December 2029) but not when it was made or when it renews.",
        impact="Sets the date by which each contract must meet paragraph 6.3 under paragraph 9.3.",
        ask_role="Head of Third-Party Risk",
        reason="missing_data",
        cites=[fact_9_3.id, unit_firm.id],
        priority="high",
        state="open",
    )
    disagreement = Disagreement.build(
        about="Which provider the firm's card payments run on",
        claims=[_claim(fact_notes), _claim(fact_service)],
        found_by={"name": "provider-cross-check", "version": "0.1.0"},
        status="open",
    )
    variant_disagreement = Disagreement.build(
        about="Two readings of paragraph 7.1 word the requirement differently",
        claims=sorted(
            (_claim(fact_7_1), _claim(fact_7_1_variant)), key=lambda c: c["judged_digest"]
        ),
        found_by={"name": "fact-variants", "version": "0.1.0"},
        status="open",
    )
    accept_7_1 = Decision.on(
        fact_7_1,
        outcome="accept",
        reason="The quote and the deadline match paragraph 7.1.",
        reviewer=REVIEWER,
        date=REVIEW_DATE,
    )
    answer = Decision.on(
        question,
        outcome="answer",
        answer="Both contracts were made in 2024, before 1 January 2027; neither renews before "
        "its end date.",
        reason="Checked against our contracts register.",
        reviewer=REVIEWER,
        date=REVIEW_DATE,
    )
    statements = [
        Statement.build(
            heading="Incident reporting",
            cites=[fact_7_1.id],
            text="Harbour Mutual Bank must notify the regulator of a major incident within "
            "4 hours of classifying it, and no later than 24 hours after first detecting it.",
        ),
        Statement.build(
            heading="Third-party contracts",
            cites=[fact_9_3.id],
            text="Contracts with material providers made before 1 January 2027 must meet "
            "paragraph 6.3 at their next renewal or by 31 December 2028, whichever is earlier.",
        ),
    ]
    brief = Brief.build(
        request="Summarise document PS26-4 for FIRM-001",
        sources=[document.id, firms.id, providers.id],
        statements=statements,
        open_question_ids=[question.id],
        model="claude-opus-5-5",
        prompt_version="1",
    )
    sign_off = SignOff.build(
        brief_id=brief.id,
        brief_digest=brief.content_digest,
        reviewer=REVIEWER,
        date=REVIEW_DATE,
        outcome="signed",
        assumptions=[
            {
                "question_id": question.id,
                "words": "Until the contracts register is checked, treat both contracts as made "
                "before 1 January 2027.",
            }
        ],
    )
    anchors = paragraph_anchors()
    document_accounting = UnitAccounting.build(
        source_id=document.id,
        units_in=len(anchors),
        with_facts=[a for a in anchors if a != "para:10.2"],
        without_facts=[
            {
                "anchor": "para:10.2",
                "reason": "Contact details only, with nothing a firm must or may do",
            }
        ],
    )
    firms_accounting = UnitAccounting.build(
        source_id=firms.id, units_in=1, with_facts=["row:FIRM-001"], without_facts=[]
    )
    return Examples(
        document=document,
        firms=firms,
        providers=providers,
        unit_7_1=_unit(document, "para:7.1", PARA_7_1),
        unit_9_3=_unit(document, "para:9.3", PARA_9_3),
        unit_firm=unit_firm,
        unit_provider=_unit(providers, "row:PROVIDER-002", PROVIDER_002_ROW),
        fact_7_1=fact_7_1,
        fact_9_3=fact_9_3,
        fact_notes=fact_notes,
        fact_service=fact_service,
        fact_small_firm=fact_small_firm,
        fact_7_1_rerun=fact_7_1_rerun,
        fact_7_1_variant=fact_7_1_variant,
        question=question,
        disagreement=disagreement,
        variant_disagreement=variant_disagreement,
        accept_7_1=accept_7_1,
        answer=answer,
        brief=brief,
        sign_off=sign_off,
        document_accounting=document_accounting,
        firms_accounting=firms_accounting,
    )
