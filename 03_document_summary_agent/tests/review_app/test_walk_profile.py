"""The firm profile: firm and provider facts are confirmed or amended once, with one reason."""

from __future__ import annotations

import csv
import io
import re

import pytest
from review_fakes import FakeRuns, examples_review
from review_fixtures import DANA, make_client
from review_helpers import RUN, SAM, decide, switch_to, text_of
from review_table_fakes import tables_review

PROFILE = f"{RUN}/review?tab=profile"
HEADING = "The firm profile the brief was written against"
KINDS = ("firm_attribute", "provider_attribute")


@pytest.fixture()
def table_runs() -> FakeRuns:
    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=tables_review())
    return runs


def facts_of(runs, *, profile: bool):
    review = runs._runs["run-1"].review
    found = [c.fact for s in review.request.statements for c in s.facts]
    return [f for f in found if (f.kind in KINDS) is profile]


def post_profile(client, runs, **fields):
    review = runs._runs["run-1"].review
    body = {
        "brief_digest": review.request.brief_digest,
        "outcome": "accept",
        "reason": "The firm and provider tables say this.",
        **fields,
    }
    return client.post(f"{RUN}/profile", data=body)


def decision_rows(html: str) -> list[str]:
    """Return the rows of the table of decisions, heading row included."""
    table = re.search(r'<table class="data" data-hook="table">.*?</table>', html, flags=re.S)
    assert table, "the page has no table of decisions"
    return re.findall(r"<tr>.*?</tr>", table.group(0), flags=re.DOTALL)


def tiles(page):
    return re.findall(r'tile-value">([^<]+)<', page.text)


def test_the_profile_tab_exists_only_when_the_brief_cites_firm_or_provider_facts(table_runs, runs):
    with_profile = make_client(table_runs).get(f"{RUN}/review")
    assert 'title="Open firm profile"' in with_profile.text
    without = make_client(runs).get(f"{RUN}/review")
    assert "Firm profile" not in without.text
    assert make_client(runs).get(f"{RUN}/review?tab=profile").status_code == 200  # falls back


def test_the_profile_tab_shows_every_firm_and_provider_fact_as_one_block(table_runs):
    page = make_client(table_runs).get(PROFILE)
    text = text_of(page.text)
    assert HEADING in text and text.count(HEADING) == 1
    for words in (
        "Harbour Mutual Bank, firm profile",
        "Total assets £9 billion",
        "Operational resilience senior manager none named",
        "NimbusCloud, contract ends 30 June 2027, material",
        "NimbusCloud, provider",
        "PayCore Ltd, provider",
        "Service card processing",
    ):
        assert words in text, words
    assert page.text.count('data-hook="profile-form"') == 1
    assert f'action="{RUN}/profile"' in page.text
    assert f'action="{RUN}/decide"' not in page.text  # no fact of the profile is decided alone


def test_a_profile_fact_in_the_brief_leads_to_the_profile_and_has_no_form_of_its_own(table_runs):
    client = make_client(table_runs)
    profile_fact = facts_of(table_runs, profile=True)[0]
    page = client.get(f"{RUN}/review")
    link = re.search(rf'href="([^"]+)" data-fact="{profile_fact.id}"', page.text)
    assert link and "tab=profile" in link.group(1)
    opened = client.get(f"{RUN}/review", params={"fact": profile_fact.id})
    assert "decision-form" not in opened.text
    assert "firm profile" in text_of(opened.text).lower()
    assert "Decide the firm profile" in text_of(opened.text)


def test_one_confirmation_records_one_decision_for_each_fact_with_one_reason(table_runs):
    client = make_client(table_runs)
    covered = facts_of(table_runs, profile=True)
    assert len(covered) == 5
    done = post_profile(client, table_runs)
    assert done.status_code == 303
    page = client.get(PROFILE)
    text = text_of(page.text)
    assert "Accepted by you, on 25 November 2026, covering 5 facts" in text
    assert "Reason given: The firm and provider tables say this." in text
    assert tiles(page)[1] == "5 of 6"
    brief = client.get(f"{RUN}/review")
    assert text_of(brief.text).count("Accepted by you") == 5
    # the decisions are held one per fact, so sign-off sends one per subject
    decide(client, table_runs._runs["run-1"].review, facts_of(table_runs, profile=False)[0])
    signed = client.post(
        f"{RUN}/sign",
        data={
            "brief_digest": table_runs._runs["run-1"].review.request.brief_digest,
            "outcome": "signed",
        },
    )
    assert signed.status_code == 303
    [(_, response)] = table_runs.submitted
    held = {d.subject_id: d for d in response.decisions}
    assert set(held) == {f.id for f in covered} | {facts_of(table_runs, profile=False)[0].id}
    shared = [held[f.id] for f in covered]
    assert {(d.outcome, d.reason, d.reviewer, d.date) for d in shared} == {
        ("accept", "The firm and provider tables say this.", DANA, "2026-11-25")
    }
    assert len({d.id for d in shared}) == 5


def test_an_amended_profile_carries_the_persons_wording_on_each_fact(table_runs):
    client = make_client(table_runs)
    refused = post_profile(client, table_runs, outcome="amend", amendment="")
    assert refused.status_code == 422
    assert "Write the amended wording in your own words." in text_of(refused.text)
    assert "profile-form" in refused.text and "Total assets" in refused.text
    done = post_profile(
        client, table_runs, outcome="amend", amendment="The senior manager is Alex Reid."
    )
    assert done.status_code == 303
    text = text_of(client.get(PROFILE).text)
    assert "Amended by you, on 25 November 2026, covering 5 facts" in text
    assert "Your wording: The senior manager is Alex Reid." in text


def test_a_profile_decision_needs_the_persons_own_reason_a_signed_in_person_and_a_current_brief(
    table_runs,
):
    client = make_client(table_runs)
    assert post_profile(client, table_runs, reason=" ").status_code == 422
    stale = client.post(
        f"{RUN}/profile",
        data={"brief_digest": "sha256:" + "ab" * 32, "outcome": "accept", "reason": "x"},
    )
    assert stale.status_code == 409
    anonymous = post_profile(make_client(table_runs, signed_in=None), table_runs)
    assert anonymous.status_code == 403
    assert tiles(client.get(PROFILE))[1] == "0 of 6"


def test_the_profile_can_be_changed_and_a_second_person_does_not_see_it_as_theirs(table_runs):
    client = make_client(table_runs)
    post_profile(client, table_runs, outcome="reject", reason="The figures are out of date.")
    assert "Rejected by you" in text_of(client.get(PROFILE).text)
    post_profile(client, table_runs, reason="Checked again against the tables.")
    text = text_of(client.get(PROFILE).text)
    assert "Accepted by you" in text and "Rejected by you" not in text
    switch_to(client, SAM)
    other = text_of(client.get(PROFILE).text)
    assert "by you" not in other and "Needs a person" in other


def test_the_next_fact_after_a_profile_decision_is_the_first_paragraph_waiting(table_runs):
    client = make_client(table_runs)
    done = post_profile(client, table_runs)
    paragraph = facts_of(table_runs, profile=False)[0]
    assert paragraph.id.replace(":", "%3A") in done.headers["location"]


def test_the_signed_page_shows_the_profile_as_one_decision_listing_the_facts_it_covered(table_runs):
    client = make_client(table_runs)
    review = table_runs._runs["run-1"].review
    post_profile(client, table_runs)
    decide(client, review, facts_of(table_runs, profile=False)[0])
    client.post(
        f"{RUN}/sign", data={"brief_digest": review.request.brief_digest, "outcome": "signed"}
    )
    page = client.get(f"{RUN}/signed")
    rows = decision_rows(page.text)
    assert len(rows) == 3  # the heading, the profile and the paragraph
    profile_row = text_of(next(r for r in rows if "Firm profile" in r))
    for name in (
        "Harbour Mutual Bank, firm profile: total assets",
        "NimbusCloud, provider: name",
        "PayCore Ltd, provider: service",
    ):
        assert name in profile_row, name
    assert "Accepted" in profile_row and "Dana Whitfield, Head of Compliance" in profile_row
    assert tiles(page)[1] == "2"  # the profile is one decision, as the table shows it
    exported = list(csv.reader(io.StringIO(client.get(f"{RUN}/decisions.csv").text)))
    assert len(exported) == 3


def test_decisions_that_differ_are_shown_one_by_one_not_as_a_profile(table_runs):
    client = make_client(table_runs)
    review = table_runs._runs["run-1"].review
    for number, fact in enumerate(facts_of(table_runs, profile=True)):
        decide(client, review, fact, reason=f"Read row {number}.")
    decide(client, review, facts_of(table_runs, profile=False)[0])
    client.post(
        f"{RUN}/sign", data={"brief_digest": review.request.brief_digest, "outcome": "signed"}
    )
    rows = decision_rows(client.get(f"{RUN}/signed").text)
    assert len(rows) == 7
    assert "covering" not in text_of(client.get(PROFILE).text)


def test_a_brief_with_no_firm_or_provider_fact_has_no_profile_route_to_use(runs):
    refused = post_profile(make_client(runs), runs)
    assert refused.status_code == 422
    assert "no firm or provider facts" in text_of(refused.text)
    assert examples_review()  # the fixture builds
