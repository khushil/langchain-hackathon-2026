"""A review of sections 6 and 7 whose paragraphs show every mark of the picture of the document."""

from __future__ import annotations

from review_fakes import Review, paragraph_text, section_seven_review

from fsi_common.examples.data import build_examples
from fsi_common.ids import digest_text
from fsi_common.records import Fact, SourceUnit, UnitAccounting
from utils.records import FACT_CONTEXT

NO_FACT = "The section reader found no obligation in this paragraph."


def _failed_fact(document_id: str, digest: str) -> Fact:
    """A fact on paragraph 6.2 whose deadline check failed, so the brief cannot cite it."""
    return Fact.build(
        context=FACT_CONTEXT,
        kind="obligation",
        subject={"source_id": document_id, "anchor": "para:6.2"},
        quote="must notify the FSOA at least 60 days before",
        attributes={"requirement": ["Notify before a new arrangement"], "deadline": "60 days"},
        status={"status": "documented"},
        provenance={
            "source_id": document_id,
            "anchor": "para:6.2",
            "extractor": {"name": "section-reader", "version": "0.1.0"},
            "model": "claude-sonnet-5-5",
            "prompt_version": "1",
            "as_of": digest,
        },
        checks=[
            {"check": "quote-verbatim.v1", "outcome": "pass", "detail": "found in the unit"},
            {"check": "deadline-verbatim.v1", "outcome": "fail", "detail": "not in the unit"},
        ],
    )


def map_review() -> Review:
    """Build section 7's review with section 6 read as well.

    Paragraph 6.1 gave no fact, 6.2 gave a fact whose check failed, 7.1 carries a fact an open
    question rests on, 7.2 and 7.3 are obligations with a deadline, 7.4 an obligation without one
    and 7.5 a permission. The state holds the units and the accounting the picture is drawn from.
    """
    review = section_seven_review()
    document = build_examples().document
    state = review.state
    failed = _failed_fact(document.id, document.digest)
    state["facts"][failed.id] = [failed.to_json()]
    state["request"] = {**state["request"], "sections": ["6", "7"]}
    for anchor in ("para:6.1", "para:6.2"):
        text = paragraph_text(anchor.removeprefix("para:"))
        unit = SourceUnit.build(source_id=document.id, anchor=anchor, text_digest=digest_text(text))
        state["units"][unit.id], state["unit_text"][unit.id] = unit.to_json(), text
    found = [a for a in state["accounting"][document.id]["with_facts"]] + ["para:6.2"]
    state["accounting"][document.id] = UnitAccounting.build(
        source_id=document.id,
        units_in=len(found) + 1,
        with_facts=found,
        without_facts=[{"anchor": "para:6.1", "reason": NO_FACT}],
    ).to_json()
    return review
