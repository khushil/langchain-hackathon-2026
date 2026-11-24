"""The compliance brief's pages in a real browser, at 1366 by 768 and 1920 by 1080."""

from __future__ import annotations

import csv
import io
import re

import pytest
from review_browser_support import SIZES, Served, shot  # noqa: F401

from fsi_common.app.browser_checks import (
    answer_problems,
    clickable_problems,
    clipped_problems,
    contrast_problems,
    type_floor_problems,
)

BASE = "/compliance-brief"
# Every page route, with whether its detail may run below the fold.
PAGES = {
    "start": (f"{BASE}/", True),
    "running": (f"{BASE}/runs/run-2", False),
    "failed": (f"{BASE}/runs/run-3", False),
    "review": (f"{BASE}/runs/run-1/review", False),
    "questions": (f"{BASE}/runs/run-1/review?tab=questions", False),
    "signoff": (f"{BASE}/runs/run-1/review?tab=signoff", False),
    "facts": (f"{BASE}/runs/run-1/facts", False),
    "signed": (f"{BASE}/runs/run-4/signed", True),
    "about": ("/about", False),
    "home": ("/", False),
    "signin": ("/signin", False),
    "notfound": (f"{BASE}/runs/none/review", False),
}
# Routes that answer a form or an export, or lead to another page, and how each is tested.
FLOW = "test_the_whole_review_through_the_browser"
CSV = "test_the_csv_of_each_table_holds_the_rows_the_table_shows"
OTHER_ROUTES = {
    "/signin (POST)": FLOW,
    "/signout (POST)": "shell: test_a_person_signs_in_and_out_with_the_keyboard_and_a_real_click",
    f"{BASE}/runs (POST)": "pages: test_starting_a_brief_*",
    f"{BASE}/runs.csv": CSV,
    f"{BASE}/runs/{{thread}}": "pages: test_a_run_waiting_for_review_leads_to_the_review",
    f"{BASE}/runs/{{thread}}/decide": FLOW,
    f"{BASE}/runs/{{thread}}/answer": FLOW,
    f"{BASE}/runs/{{thread}}/assume": "pages: test_an_open_question_is_answered_or_accepted",
    f"{BASE}/runs/{{thread}}/sign": FLOW,
    f"{BASE}/runs/{{thread}}/facts.csv": CSV,
    f"{BASE}/runs/{{thread}}/decisions.csv": CSV,
    "/static": "every page loads app.css",
    f"{BASE}/static": "every page loads review.css",
}
ADVICE = "regulatory advice"


def _routes(app, prefix=""):
    from starlette.routing import Mount, Route

    for route in app.routes:
        if isinstance(route, Mount):
            yield from _routes(route, prefix + route.path)
        elif isinstance(route, Route):
            for method in sorted(route.methods - {"HEAD"}):
                yield f"{prefix}{route.path} ({method})"


def test_every_route_of_the_application_is_tested(served):
    found = set()
    for item in _routes(served.app):
        path = item.split(" (")[0]
        found.add(path)
    page_paths = {
        p.split("?")[0]
        .replace("run-1", "{thread}")
        .replace("run-2", "{thread}")
        .replace("run-3", "{thread}")
        .replace("run-4", "{thread}")
        .replace("none", "{thread}")
        for p, _ in PAGES.values()
    }
    covered = page_paths | {k.split(" (")[0] for k in OTHER_ROUTES} | {BASE + "/", BASE + "/runs"}
    missing = sorted(p for p in found if p not in covered and p != "/")
    assert missing == [], f"Routes with no browser or client test named: {missing}"
    assert len(PAGES) + len(OTHER_ROUTES) >= len(found)


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("name", sorted(PAGES))
def test_each_page_holds_the_answer_in_view_and_passes_every_sweep(browser, served, name, size):
    path, tall = PAGES[name]
    context, page = served.open(browser, size)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(served.base_url + path)
    shot(page, name, size)
    assert answer_problems(page, tall_exhibit_allowed=tall) == []
    assert type_floor_problems(page) == []
    assert contrast_problems(page) == []
    assert clipped_problems(page) == []
    assert clickable_problems(page) == []
    assert errors == []
    context.close()


def _independent_counts(state):
    brief = state["draft_brief"]
    cited = {fid for s in brief["statements"] for fid in s["cites"]}
    return len(brief["statements"]), len(cited), len(brief["open_question_ids"])


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_the_headline_numbers_equal_an_independent_count_of_the_records(browser, served, size):
    statements, facts, questions = _independent_counts(served.runs.result("run-1"))
    context, page = served.open(browser, size)
    page.goto(served.base_url + PAGES["review"][0])
    sentence = page.inner_text("[data-hook=sentence]")
    assert f"{statements} statements resting on {facts} facts" in sentence
    tiles = [t.inner_text().split("\n")[0] for t in page.locator("[data-hook=tile]").all()]
    assert tiles == [str(statements), f"0 of {facts}", f"0 of {questions}"]
    assert f"{facts} facts and {questions} question still need your decision" in sentence
    page.goto(served.base_url + PAGES["start"][0])
    tiles = [t.inner_text().split("\n")[0] for t in page.locator("[data-hook=tile]").all()]
    assert tiles == ["4", "1", "1"]  # four runs, one waiting for review, one signed
    context.close()


def test_a_real_click_on_a_fact_opens_its_paragraph_changes_the_address_and_survives_a_reload(
    browser, served
):
    review = served.runs._runs["run-1"].review
    target = review.request.statements[2].facts[0].fact
    context, page = served.open(browser, SIZES[0])
    page.goto(served.base_url + PAGES["review"][0])
    page.click(f'[data-fact="{target.id}"]')
    page.wait_for_url(re.compile(r"fact="))
    assert f"fact={target.id.replace(':', '%3A')}" in page.url
    assert page.inner_text("[data-hook=paragraph] mark") == target.quote
    assert "Paragraph 7.3" in page.inner_text("[data-hook=source]")
    assert page.get_attribute(f'[data-fact="{target.id}"]', "aria-current") == "true"
    page.reload()
    assert page.inner_text("[data-hook=paragraph] mark") == target.quote
    assert page.get_attribute(f'[data-fact="{target.id}"]', "aria-current") == "true"
    context.close()


def test_a_fact_opens_from_the_keyboard(browser, served):
    review = served.runs._runs["run-1"].review
    target = review.request.statements[1].facts[0].fact
    context, page = served.open(browser, SIZES[0])
    page.goto(served.base_url + PAGES["review"][0])
    page.focus(f'[data-fact="{target.id}"]')
    page.keyboard.press("Enter")
    page.wait_for_url(re.compile(r"fact="))
    assert page.inner_text("[data-hook=paragraph] mark") == target.quote
    context.close()


def test_the_whole_review_through_the_browser(browser, served):
    review = served.runs._runs["run-1"].review
    facts = [c.fact for s in review.request.statements for c in s.facts]
    context, page = served.open(browser, SIZES[0], signed_in=False)
    page.goto(served.base_url + PAGES["review"][0])
    page.click("header >> text=Sign in")
    page.fill("#name", "Dana Whitfield")
    page.fill("#role", "Head of Compliance")
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/review"))
    for i, fact in enumerate(facts, 1):
        page.click(f'[data-fact="{fact.id}"]')
        page.wait_for_selector("[data-hook=decision-form]")
        page.click("label:has-text('Accept')")
        page.fill("#reason", f"Quote {i} matches its paragraph.")
        page.click("text=Record my decision")
        page.wait_for_load_state()
    tiles = [t.inner_text().split("\n")[0] for t in page.locator("[data-hook=tile]").all()]
    assert tiles[1] == f"{len(facts)} of {len(facts)}"
    page.click("nav.tabs >> text=Open questions")
    page.fill("#answer-1", "Retail payments and mobile banking.")
    page.fill("#basis-1", "The firm's service register.")
    page.click("text=Record my answer")
    page.wait_for_load_state()
    assert "Every fact and question is settled" in page.inner_text("[data-hook=sentence]")
    page.click("nav.tabs >> text=Sign-off")
    page.click("text=Sign the brief")
    page.wait_for_url(re.compile(r"/signed$"))
    record = page.inner_text("[data-hook=sign-off-record]")
    assert "Dana Whitfield" in record and "Head of Compliance" in record
    assert review.request.brief_digest in record
    [(thread, response)] = [s for s in served.runs.submitted if s[0] == "run-1"]
    assert len(response.decisions) == len(facts) + 1
    assert response.sign_off.outcome == "signed"
    shot(page, "signed-after-flow", SIZES[0])
    context.close()


def test_a_decision_is_refused_in_words_when_the_person_has_not_given_a_reason(browser, served):
    context, page = served.open(browser, SIZES[0])
    page.goto(served.base_url + PAGES["review"][0])
    page.click("label:has-text('Accept')")
    page.evaluate("() => document.querySelector('#reason').removeAttribute('required')")
    page.click("text=Record my decision")
    page.wait_for_selector("[data-hook=form-problem]")
    assert "Write your reason in your own words." in page.inner_text("[data-hook=form-problem]")
    context.close()


def _table_rows(page):
    return [
        [c.inner_text().strip() for c in row.locator("td").all()]
        for row in page.locator("table[data-hook=table] tbody tr").all()
    ]


def _csv_rows(page, href):
    body = page.request.get(href).text()
    return list(csv.reader(io.StringIO(body)))[1:]


@pytest.mark.parametrize("name", ["start", "facts", "signed"])
def test_the_csv_of_each_table_holds_the_rows_the_table_shows(browser, served, name):
    context, page = served.open(browser, SIZES[0])
    page.goto(served.base_url + PAGES[name][0])
    header = page.locator("table[data-hook=table] thead th a").nth(1)
    header.click()
    page.wait_for_url(re.compile(r"sort="))
    shown = _table_rows(page)
    href = page.get_attribute("a[data-hook=export]", "href")
    assert _csv_rows(page, served.base_url + href) == shown
    assert len(shown) >= 1
    context.close()


def test_nothing_is_fetched_from_outside_on_any_page_of_the_topic(browser, served):
    context, page = served.open(browser, SIZES[0])
    outside = []
    context.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.url.startswith(served.base_url)
            else (outside.append(route.request.url), route.abort())
        ),
    )
    for path, _ in PAGES.values():
        page.goto(served.base_url + path)
    assert outside == []
    context.close()


def test_the_advice_sentence_is_on_the_about_page_alone(browser, served):
    context, page = served.open(browser, SIZES[0])
    holders = []
    for name, (path, _) in PAGES.items():
        page.goto(served.base_url + path)
        if ADVICE in page.inner_text("body").lower():
            holders.append(name)
    assert holders == ["about"]
    context.close()


def test_the_reduced_motion_setting_leaves_nothing_moving(browser, served):
    context = browser.new_context(viewport={"width": 1366, "height": 768}, reduced_motion="reduce")
    page = context.new_page()
    page.goto(served.base_url + PAGES["start"][0])
    assert page.evaluate("() => document.getAnimations().length") == 0
    context.close()


EXPLAINING = (
    "worked out",
    "how we work",
    "caveat",
    "disclaimer",
    "drafting note",
    "this page shows",
)


def test_no_page_explains_the_method_or_carries_a_caveat(browser, served):
    context, page = served.open(browser, SIZES[0])
    found = {}
    for name, (path, _) in PAGES.items():
        page.goto(served.base_url + path)
        text = page.inner_text("body").lower()
        hits = [phrase for phrase in EXPLAINING if phrase in text]
        if hits:
            found[name] = hits
    assert found == {}
    context.close()
