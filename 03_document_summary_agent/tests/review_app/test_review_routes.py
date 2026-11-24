"""Every route of the application is reached by a request, and has a test named for what it does."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest
from review_fixtures import make_client
from review_helpers import BASE, RUN, runs_for_every_page
from review_table_fakes import tables_review

from fsi_common.examples.data import build_examples
from review_app.plugin import build_plugin  # noqa: F401  (the plug-in is part of the application)

EX = build_examples()
HERE = Path(__file__).parent
SHELL = Path(__file__).resolve().parents[3] / "fsi_common" / "tests" / "app"
ROUTES = "test_review_routes.py"
SHELL_TESTS = "test_app_shell.py"
PAGES = "test_review_pages.py"
START = "test_start_pages.py"
PEOPLE = "test_review_people.py"
THIS_LOOP = "test_every_route_of_the_application_answers_the_request_its_state_needs"


@dataclass(frozen=True)
class Reach:
    """How one route is reached: the request, what it must answer, and the test named for it."""

    request: object  # a function of the client that makes the request
    answers: frozenset[int]
    test: tuple[Path, str]


def _post(path, **data):
    return lambda c: c.post(path, data=data)


def _sections(**extra):
    return {"document_id": "PS26-4", "firm_id": "FIRM-001", "sections": ["7"], **extra}


def _digest(c, runs):
    return runs._runs["run-1"].review.request.brief_digest


def _post_profile(c, runs):
    """Post a decision on the firm profile of a run that cites firm and provider facts."""
    review = tables_review()
    runs.add("run-5", "awaiting_review", review=review)
    return c.post(
        f"{BASE}/runs/run-5/profile",
        data={
            "brief_digest": review.request.brief_digest,
            "outcome": "accept",
            "reason": "The tables say this.",
        },
    )


def table():
    """Return each route of the application with the request that reaches it."""
    q = EX.fact_7_1
    both = "test_the_facts_table_lists_every_fact_sorts_and_exports_the_same_rows"
    answer = "test_an_open_question_is_answered_or_accepted_as_an_assumption_in_the_persons_words"
    signing = (
        "test_signing_sends_the_persons_decisions_and_sign_off_to_the_engine_and_shows_the_record"
    )
    return {
        "GET /": Reach(
            lambda c, r: c.get("/"),
            frozenset({200}),
            (SHELL / SHELL_TESTS, "test_home_lists_the_topic_and_the_layout_carries_one_demo_tag"),
        ),
        "GET /about": Reach(
            lambda c, r: c.get("/about"),
            frozenset({200}),
            (
                SHELL / SHELL_TESTS,
                "test_about_holds_the_advice_sentence_and_each_topics_paragraphs",
            ),
        ),
        "GET /signin": Reach(
            lambda c, r: c.get("/signin"),
            frozenset({200}),
            (
                SHELL / SHELL_TESTS,
                "test_every_page_has_an_answer_sentence_at_most_three_tiles_and_one_exhibit",
            ),
        ),
        "POST /signin": Reach(
            lambda c, r: c.post(
                "/signin", data={"name": "Sam Okoye", "role": "Compliance Officer"}
            ),
            frozenset({303}),
            (
                SHELL / SHELL_TESTS,
                "test_sign_in_keeps_the_person_in_a_signed_cookie_and_sign_out_removes_it",
            ),
        ),
        "POST /signout": Reach(
            lambda c, r: c.post("/signout"),
            frozenset({303}),
            (
                SHELL / SHELL_TESTS,
                "test_sign_in_keeps_the_person_in_a_signed_cookie_and_sign_out_removes_it",
            ),
        ),
        "GET /static (files)": Reach(
            lambda c, r: c.get("/static/app.css"),
            frozenset({200}),
            (
                SHELL / SHELL_TESTS,
                "test_the_topic_page_renders_inside_the_layout_and_its_static_file_is_served",
            ),
        ),
        f"GET {BASE}/": Reach(
            lambda c, r: c.get(f"{BASE}/"),
            frozenset({200}),
            (HERE / START, "test_start_page_says_what_is_waiting_and_lists_every_run"),
        ),
        f"POST {BASE}/runs": Reach(
            lambda c, r: (
                setattr(r._runs["run-3"], "status", "signed"),
                c.post(f"{BASE}/runs", data=_sections()),
            )[1],
            frozenset({303}),
            (HERE / START, "test_starting_a_brief_for_one_section_sends_the_section_filter"),
        ),
        f"GET {BASE}/runs.csv": Reach(
            lambda c, r: c.get(f"{BASE}/runs.csv"),
            frozenset({200}),
            (HERE / START, "test_the_runs_table_exports_the_rows_it_shows"),
        ),
        f"GET {BASE}/runs/{{thread}}": Reach(
            lambda c, r: c.get(f"{BASE}/runs/run-3"),
            frozenset({200}),
            (HERE / START, "test_a_run_being_written_shows_its_progress_and_refreshes_itself"),
        ),
        f"GET {BASE}/runs/{{thread}}/review": Reach(
            lambda c, r: c.get(f"{RUN}/review"),
            frozenset({200}),
            (HERE / PAGES, "test_the_review_page_answers_in_one_sentence_built_with_its_tiles"),
        ),
        f"POST {BASE}/runs/{{thread}}/profile": Reach(
            _post_profile,
            frozenset({303}),
            (
                HERE / "test_walk_profile.py",
                "test_one_confirmation_records_one_decision_for_each_fact_with_one_reason",
            ),
        ),
        f"POST {BASE}/runs/{{thread}}/decide": Reach(
            lambda c, r: c.post(
                f"{RUN}/decide",
                data={
                    "brief_digest": _digest(c, r),
                    "fact_id": q.id,
                    "outcome": "accept",
                    "reason": "Read.",
                },
            ),
            frozenset({303}),
            (
                HERE / PAGES,
                "test_accepting_a_fact_records_the_persons_decision_and_moves_to_the_next_fact",
            ),
        ),
        f"POST {BASE}/runs/{{thread}}/answer": Reach(
            lambda c, r: c.post(
                f"{RUN}/answer",
                data={
                    "brief_digest": _digest(c, r),
                    "question_id": r._runs["run-1"].review.question.id,
                    "answer": "Yes",
                    "reason": "Register.",
                },
            ),
            frozenset({303}),
            (HERE / PAGES, answer),
        ),
        f"POST {BASE}/runs/{{thread}}/assume": Reach(
            lambda c, r: c.post(
                f"{RUN}/assume",
                data={
                    "brief_digest": _digest(c, r),
                    "question_id": r._runs["run-1"].review.question.id,
                    "words": "Assumed.",
                },
            ),
            frozenset({303}),
            (HERE / PAGES, answer),
        ),
        f"POST {BASE}/runs/{{thread}}/sign": Reach(
            lambda c, r: c.post(
                f"{RUN}/sign",
                data={"brief_digest": _digest(c, r), "outcome": "returned", "reason": "Reread."},
            ),
            frozenset({303}),
            (HERE / PAGES, signing),
        ),
        f"GET {BASE}/runs/{{thread}}/facts": Reach(
            lambda c, r: c.get(f"{RUN}/facts"), frozenset({200}), (HERE / PAGES, both)
        ),
        f"GET {BASE}/runs/{{thread}}/facts.csv": Reach(
            lambda c, r: c.get(f"{RUN}/facts.csv"), frozenset({200}), (HERE / PAGES, both)
        ),
        f"GET {BASE}/runs/{{thread}}/decisions.csv": Reach(
            lambda c, r: c.get(f"{BASE}/runs/run-2/decisions.csv"),
            frozenset({200}),
            (
                HERE / PEOPLE,
                "test_where_a_fact_has_two_decisions_the_pages_show_the_sign_off_reviewers",
            ),
        ),
        f"GET {BASE}/runs/{{thread}}/signed": Reach(
            lambda c, r: c.get(f"{BASE}/runs/run-2/signed"),
            frozenset({200}),
            (HERE / PAGES, signing),
        ),
        f"GET {BASE}/static (files)": Reach(
            lambda c, r: c.get(f"{BASE}/static/review.css"),
            frozenset({200}),
            (HERE / ROUTES, THIS_LOOP),
        ),
    }


def routes_of(app, prefix: str = "") -> set[str]:
    """Return every route of an application as ``METHOD path``, static folders included."""
    from starlette.routing import Mount, Route
    from starlette.staticfiles import StaticFiles

    found = set()
    for route in app.routes:
        if isinstance(route, Mount):
            if isinstance(getattr(route, "app", None), StaticFiles):
                found.add(f"GET {prefix}{route.path} (files)")
            else:
                found |= routes_of(route, prefix + route.path)
        elif isinstance(route, Route):
            found |= {f"{m} {prefix}{route.path}" for m in route.methods - {"HEAD"}}
    return found


def test_the_listing_of_routes_sees_every_kind_of_route(client):
    listed = routes_of(client.app)
    assert "GET /" in listed and "POST /signin" in listed
    assert f"GET {BASE}/runs/{{thread}}/review" in listed
    assert "GET /static (files)" in listed and f"GET {BASE}/static (files)" in listed
    assert not any("HEAD" in item for item in listed)


def test_every_route_of_the_application_is_in_the_table_and_every_entry_is_a_route(client):
    listed, tabled = routes_of(client.app), set(table())
    assert sorted(listed - tabled) == [], "routes no request reaches"
    assert sorted(tabled - listed) == [], "entries for routes the application does not have"


@pytest.mark.parametrize("route", sorted(table()))
def test_every_route_of_the_application_answers_the_request_its_state_needs(route):
    runs = runs_for_every_page()
    reach = table()[route]
    response = reach.request(make_client(runs), runs)
    assert response.status_code in reach.answers, (route, response.status_code)
    assert "There is nothing at this address." not in response.text, route


def _tests_in(path: Path) -> set[str]:
    return {
        node.name
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }


@pytest.mark.parametrize("route", sorted(table()))
def test_every_route_has_a_test_named_for_it_that_exists(route):
    path, name = table()[route].test
    assert path.is_file(), f"{route}: {path} is not a file"
    assert name in _tests_in(path), f"{route}: {name} is not a test of {path.name}"


def test_the_check_for_a_named_test_sees_a_test_that_is_not_there(tmp_path):
    module = tmp_path / "test_x.py"
    module.write_text("def test_present():\n    pass\n\ndef _test_taken_out():\n    pass\n")
    assert "test_present" in _tests_in(module)
    assert "test_taken_out" not in _tests_in(module)
    assert "_test_taken_out" not in _tests_in(module)
