"""The user guide's policy steps, followed on the pages: each quoted phrase is there."""

from __future__ import annotations

from pathlib import Path

import pytest
from policy_pages_support import BASE, CORPUS, make_app, text_of, write_fake, write_left_out

GUIDE = (Path(__file__).resolve().parents[3] / "docs" / "user-guide.md").read_text("utf-8")
SECTION = GUIDE[GUIDE.index("## Policy assessment") : GUIDE.index("## KYC onboarding")]


@pytest.fixture(scope="module")
def pages(tmp_path_factory):
    bundle, root = write_fake(tmp_path_factory.mktemp("guide"))
    client, _ = make_app(root)
    return bundle, client


def seen(client, address: str) -> str:
    reply = client.get(address)
    assert reply.status_code == 200, address
    return " ".join(text_of(reply.text).replace("&#39;", "'").replace("&#34;", '"').split())


def assert_on(page: str, *phrases: str, where: str = SECTION) -> None:
    for phrase in phrases:
        assert phrase in page, f"the page does not say: {phrase}"
        assert phrase in where, f"the guide does not quote: {phrase}"


def test_the_picture_says_what_steps_one_and_two_say(pages):
    _, client = pages
    assert_on(
        seen(client, BASE),
        "Obligations that apply",
        "With a gap",
        "Gaps decided",
        "101 of 219 DORA obligations apply",
        "21 of 422 AI Act obligations apply",
        "97 of 97 SS1/23 obligations apply",
        "Found",
        "First gap without your decision",
    )


def test_an_assessment_page_says_what_step_three_and_four_say(pages):
    _, client = pages
    page = seen(client, f"{BASE}/obligations/DORA/art:30/2")
    assert_on(
        page,
        "The points of the provision",
        "Your decision",
        "Record my decision",
        "Next gap without your decision",
    )
    assert "clauses kept and" in page and "clauses kept and" in SECTION


def test_the_register_clauses_and_graph_say_what_steps_five_to_seven_say(pages):
    _, client = pages
    assert_on(
        seen(client, f"{BASE}/register"),
        "738 of 1585 units of DORA, the AI Act and SS1/23 are obligations: 219 apply to "
        "Harbour Mutual Bank, 517 do not and 2 are left to a person.",
        "Questions for you",
        "Does DORA Article 26(1) apply to Harbour Mutual Bank?",
        "Does AI Act Article 50(2) apply to Harbour Mutual Bank?",
        "Export CSV",
    )
    assert "Clauses" in seen(client, f"{BASE}/clauses")
    assert "Graph" in seen(client, f"{BASE}/graph")


def test_the_gap_report_says_what_steps_eight_and_nine_say(pages):
    _, client = pages
    assert_on(
        seen(client, f"{BASE}/gap-report"),
        "The gap report cannot be signed yet:",
        "Sign the gap report",
        "Return the gap report",
        "Why you are returning the gap report, if you return it",
    )


def test_the_refusals_the_guide_names_are_the_ones_the_pages_give(pages):
    bundle, client = pages
    assessment = next(a for a in bundle.assessments if a.state != "covered")
    key, _, anchor = assessment.obligation_id.partition(" ")
    stale = client.post(
        f"{BASE}/obligations/{key}/{anchor}/decide",
        data={"assessment_id": "assessment:0", "outcome": "accept", "reason": "x"},
    )
    assert_on(
        " ".join(text_of(stale.text).split()),
        "The assessment changed after you opened it, so nothing was recorded. "
        "Read it again and decide again.",
        where=GUIDE,
    )
    gone = client.get("/compliance-brief/policies/no-such-firm")
    assert gone.status_code == 404
    assert "There is no assessment of no-such-firm." in text_of(gone.text)
    assert f"There is no assessment of {CORPUS}." in SECTION + GUIDE


def test_the_guide_advises_no_delete_of_a_state_folder():
    import re

    assert re.search(r"\bdelet\w+ the (?:state )?folder", GUIDE, re.I) is None
    assert "delete the folder it names" not in GUIDE


def test_the_measures_page_and_the_left_out_line_say_what_the_guide_says(pages, tmp_path):
    _, client = pages
    assert_on(
        seen(client, f"{BASE}/measures"),
        "Seeded gaps found",
        "Covered seeds called a gap",
        "Citations that name no seeded clause",
        "Seeds found in the same state",
        "Every finding is a proposal that a person decides.",
    )
    _, root = write_left_out(tmp_path)
    left, _ = make_app(root)
    assert_on(seen(left, BASE), "SS1/23 is not included here:", "To include it:")
