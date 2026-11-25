"""The review pages: the batch with its picture, one application, and the sign-off."""

from __future__ import annotations

from urllib.parse import urlencode

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from context.reader import entries_of
from fsi_common.app import Answer, Tile, current_person, render, sign_in_address
from fsi_common.app.pages import build_table
from review_app.application_view import ApplicationView, build_application
from review_app.context import RunInfo, Services, read_run, run_tabs, run_url
from review_app.review_model import ReviewModel
from review_app.reviewing import (
    APPLICATION_COLUMNS,
    application_rows,
    load_review,
    picture_of,
    signed_decisions,
)
from review_app.run_data import read_run_data
from review_app.wording import proposal_words
from utils.kyc_state import CitedFact
from utils.records import customer_of_anchor


def waiting_questions(model: ReviewModel) -> dict[str, int]:
    """Count, for each application, the questions that still wait for a person."""
    counts: dict[str, int] = {}
    for state in model.question_states:
        if not state.settled:
            customer = customer_of_anchor(state.question.about.anchor)
            counts[customer] = counts.get(customer, 0) + 1
    return counts


def batch_table(request: Request, info: RunInfo, rows):
    """Build the table of applications, sorted as the address says."""
    sort = request.query_params.get("sort")
    descending = request.query_params.get("dir") == "desc"

    def href_for(**changes: str) -> str:
        return (
            run_url(info.thread_id, "review")
            + "?"
            + urlencode({**dict(request.query_params), **changes})
        )

    return build_table(
        APPLICATION_COLUMNS,
        rows,
        sort=sort,
        descending=descending,
        href_for=href_for,
        export_href=run_url(info.thread_id, "applications.csv")
        + (f"?sort={sort}&dir={'desc' if descending else 'asc'}" if sort else ""),
        caption="Applications in the batch",
        empty="The batch holds no application.",
    )


def next_to_decide(model: ReviewModel, customer: str) -> str | None:
    """Return the customer of the next application, after this one, that needs a decision."""
    waiting = [customer_of_anchor(c.fact.subject.anchor) for c in model.facts_waiting]
    after = [c for c in waiting if c > customer] + [c for c in waiting if c < customer]
    return after[0] if after else None


class ReviewPages:
    """The review pages, bound to the services; the recording routes redraw them on a refusal."""

    def __init__(self, services: Services) -> None:
        self.services = services

    def _batch_context(
        self, request: Request, info: RunInfo, model: ReviewModel, **problem
    ) -> dict:
        proposals = {f: c.fact for f, c in model.proposals.items()}
        rows = application_rows(
            info, proposals, waiting_questions(model), model, current_person(request)
        )
        return {
            "page_title": "Review the batch",
            "answer": model.answer(len(entries_of())),
            "model": model,
            "info": info,
            "tab": "applications",
            "tabs_for": run_tabs(info.thread_id, info.status),
            "picture": picture_of(info, model.settled_questions()),
            "table": batch_table(request, info, rows),
            "thread": info.thread_id,
            "brief_digest": model.request.brief_digest,
            "form_error": problem.get("form_error"),
            "form_values": problem.get("form_values") or {},
            "sign_in": sign_in_address(request),
        }

    def batch(self, request: Request, *, status: int = 200, **problem) -> Response:
        """Draw the batch page: the picture, then the table of applications."""
        loaded = load_review(self.services, request.path_params["thread"], current_person(request))
        if isinstance(loaded, Response):
            return loaded
        info, _, model = loaded
        context = self._batch_context(request, info, model, **problem)
        return render(request, "kyc/batch.html", context, status=status)

    def signoff(self, request: Request, *, status: int = 200, **problem) -> Response:
        """Draw the sign-off page."""
        loaded = load_review(self.services, request.path_params["thread"], current_person(request))
        if isinstance(loaded, Response):
            return loaded
        info, _, model = loaded
        context = {
            **self._batch_context(request, info, model, **problem),
            "page_title": "Sign the batch",
            "tab": "signoff",
        }
        return render(request, "kyc/signoff.html", context, status=status)

    def _application_context(
        self,
        request: Request,
        info: RunInfo,
        view: ApplicationView,
        model: ReviewModel | None,
        **problem,
    ) -> dict:
        thread = info.thread_id
        cited: CitedFact | None = model.proposals.get(view.proposal.id) if model else None
        decided = {} if model is not None else signed_decisions(info)
        questions = len(view.questions)
        settled = (
            sum(model.question_state(q.question.id).settled for q in view.questions)
            if model
            else questions
        )
        passed = sum(d.passed for d in view.details)
        answer = Answer(
            sentence=view.sentence,
            tiles=(
                Tile(
                    "Details that passed their checks",
                    f"{passed} of {len(view.details)}",
                    "failed" if passed < len(view.details) else "normal",
                ),
                Tile("Screenings kept as facts", str(len(view.screenings))),
                Tile(
                    "Questions settled",
                    f"{settled} of {questions}",
                    "needs_person" if settled < questions else "normal",
                ),
            ),
        )
        awaiting = info.status == "awaiting_review"
        following = next_to_decide(model, view.customer_id) if model else None
        return {
            "page_title": f"Application {view.customer_id}",
            "answer": answer,
            "view": view,
            "model": model,
            "state": model.fact_states.get(view.proposal.id) if model else None,
            "cited": cited,
            "answers": {s: d for s, d in decided.items() if s.startswith("question:")},
            "signed_decision": decided.get(view.proposal.id),
            "awaiting": awaiting,
            "info": info,
            "thread": thread,
            "tabs_for": run_tabs(thread, info.status),
            "batch_href": run_url(thread, "review" if awaiting else "signed"),
            "proposal_words": proposal_words(view.proposal),
            "brief_digest": model.request.brief_digest if model else "",
            "next_href": run_url(thread, "applications", following) if following else None,
            "form_error": problem.get("form_error"),
            "form_values": problem.get("form_values") or {},
            "error_target": problem.get("error_target"),
            "sign_in": sign_in_address(request),
        }

    def application(self, request: Request, *, status: int = 200, **problem) -> Response:
        """Draw one application's page, for a batch waiting for review or one finished."""
        thread, customer = request.path_params["thread"], request.path_params["customer"]
        info = read_run(self.services, thread)
        if info.status in {"running", "failed"}:
            raise HTTPException(404, "The batch has no applications to show yet.")
        data = read_run_data(info.state)
        view = build_application(data, info.state.get("readings", {}), customer)
        if view is None:
            raise HTTPException(404, f"There is no application {customer} in this batch.")
        model = None
        if info.status == "awaiting_review":
            loaded = load_review(self.services, thread, current_person(request))
            if isinstance(loaded, Response):
                return loaded
            model = loaded[2]
        context = self._application_context(request, info, view, model, **problem)
        return render(request, "kyc/application.html", context, status=status)

    def routes(self) -> list[Route]:
        """Return the review pages' routes."""
        return [
            Route("/runs/{thread}/review", lambda request: self.batch(request)),
            Route("/runs/{thread}/signoff", lambda request: self.signoff(request)),
            Route(
                "/runs/{thread}/applications/{customer}", lambda request: self.application(request)
            ),
        ]
