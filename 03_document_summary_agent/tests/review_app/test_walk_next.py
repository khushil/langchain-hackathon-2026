"""After a decision the panel opens the first fact still waiting; the form is in view."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from review_fixtures import make_client
from review_helpers import RUN, decide
from test_review_browser import PAGES


def opened(response) -> str:
    """Return the fact id a redirect after a decision opens."""
    return parse_qs(urlparse(response.headers["location"]).query)["fact"][0]


def test_a_decision_opens_the_first_fact_still_waiting_not_the_one_after_it(section7_runs):
    review = section7_runs._runs["run-1"].review
    facts = [c.fact for s in review.request.statements for c in s.facts]
    client = make_client(section7_runs)
    third = decide(client, review, facts[2])
    assert opened(third) == facts[0].id
    first = decide(client, review, facts[0])
    assert opened(first) == facts[1].id
    second = decide(client, review, facts[1])
    assert opened(second) == facts[3].id  # the third is decided, so the first still waiting


def test_the_last_decision_stays_on_the_fact_decided(section7_runs):
    review = section7_runs._runs["run-1"].review
    facts = [c.fact for s in review.request.statements for c in s.facts]
    client = make_client(section7_runs)
    for fact in facts[:-1]:
        decide(client, review, fact)
    last = decide(client, review, facts[-1])
    assert opened(last) == facts[-1].id


def test_the_next_fact_link_still_goes_to_the_fact_after_the_one_open(section7_runs):
    review = section7_runs._runs["run-1"].review
    facts = [c.fact for s in review.request.statements for c in s.facts]
    page = make_client(section7_runs).get(f"{RUN}/review", params={"fact": facts[1].id})
    link = re.search(r'href="([^"]+)" title="Open the next fact that needs a decision"', page.text)
    assert link and facts[2].id.replace(":", "%3A") in link.group(1)


def test_the_form_is_in_view_when_a_fact_is_opened_at_1366_by_768(browser, served):
    review = served.runs._runs["run-1"].review
    facts = [c.fact for s in review.request.statements for c in s.facts]
    context, page = served.open(browser, (1366, 768))
    for fact in facts:
        page.goto(served.base_url + PAGES["review"][0] + f"?fact={fact.id}")
        pane = page.locator("aside.source").bounding_box()
        for selector in ("#reason", "text=Record my decision"):
            box = page.locator(selector).bounding_box()
            assert box["y"] >= pane["y"], (fact.id, selector)
            assert box["y"] + box["height"] <= pane["y"] + pane["height"], (fact.id, selector)
            assert box["y"] + box["height"] <= 768, (fact.id, selector)
    context.close()


def test_the_amended_wording_box_shows_once_amend_is_chosen(browser, served):
    review = served.runs._runs["run-1"].review
    fact = review.request.statements[0].facts[0].fact
    context, page = served.open(browser, (1366, 768))
    page.goto(served.base_url + PAGES["review"][0] + f"?fact={fact.id}")
    assert not page.locator("#amendment").is_visible()
    page.click("label:has-text('Amend')")
    assert page.locator("#amendment").is_visible()
    page.click("label:has-text('Accept')")
    assert not page.locator("#amendment").is_visible()
    context.close()
