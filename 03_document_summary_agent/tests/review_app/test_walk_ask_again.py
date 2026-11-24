"""A fact the model worded differently is asked again, with the earlier decision and the change."""

from __future__ import annotations

from review_fakes import FakeRuns, examples_review
from review_fixtures import make_client
from review_helpers import RUN, text_of

from fsi_common.examples.data import build_examples
from fsi_common.records import Decision


def test_an_amended_fact_that_was_worded_differently_shows_who_amended_it_when_and_what_changed():
    ex = build_examples()
    earlier = Decision.on(
        ex.fact_7_1_variant,
        outcome="amend",
        amendment="Notify within four hours.",
        reason="The cause needs the firm's wording.",
        reviewer=ex.accept_7_1.reviewer,
        date="2026-11-24",
    )
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=examples_review(earlier={ex.fact_7_1.id: earlier}))
    client = make_client(runs)
    page = client.get(f"{RUN}/review", params={"fact": ex.fact_7_1.id})
    text = text_of(page.text)
    assert "Amended by Dana Whitfield, Head of Compliance, on 24 November 2026" in text
    assert "Reason given: The cause needs the firm's wording." in text.replace("&#39;", "'")
    assert "Since then these changed: Requirement." in text
    assert 'data-state="carried"' not in page.text
    assert "Needs a person" in page.text
    assert text.count("0 of 2") == 1  # the tile counts it as still to decide
