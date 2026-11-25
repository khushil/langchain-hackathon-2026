"""The review page, where a named person reads the brief, opens each transaction and decides."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from fsi_common.app import Cell, Column, current_person, render, sign_in_address
from fsi_common.app.pages import build_table, table_csv
from fsi_common.app.rendering import long_date
from fsi_common.records import Person
from review_app import review_route
from review_app.context import (
    PREFIX,
    STATE_ERRORS,
    RunInfo,
    Services,
    earlier_decisions,
    plain_error,
    read_run,
    run_url,
    runs_of,
    state_unavailable,
)
from review_app.drafts import DraftFileError
from review_app.pages import review_picture, rows_of, statement_items, unassessed_items
from review_app.review_model import ReviewModel
from review_app.review_route import ReviewInputError
from review_app.views import assessment_view, final_word, transaction_of
from utils.review import ReviewMismatchError, ReviewRequest
from workflow.runs import NotAwaitingReviewError, RunNotFoundError

LOG = logging.getLogger("review_app.routes_review")
TABS = ("brief", "questions", "history", "signoff")
STALE = (
    "The brief changed after you opened it, so nothing was recorded. Read it again; decisions you "
    "made on transactions that did not change are kept."
)
SIGN_IN_FIRST = "Sign in with your name and role before you decide on a brief."
HISTORY_COLUMNS = (
    Column("transaction", "Transaction"),
    Column("decision", "Decision"),
    Column("by", "Made by"),
    Column("date", "Date"),
    Column("reason", "Reason"),
)
NO_ASSESSMENT = (
    "The assessor left nothing usable for this transaction, so a person decides it by answering "
    "the question."
)


def no_such_run(thread: str) -> HTTPException:
    """Return the error that says in words that the engine has no such run."""
    return HTTPException(404, f"There is no run {thread}.")


def run_tabs(thread_id: str, status: str) -> list[tuple[str, str, str]]:
    """Return the parts of a run's pages as key, label and address.

    Args:
        thread_id: The run.
        status: The run's status.

    Returns:
        The tabs for a brief awaiting review, or the one tab of a brief that has been finished.
    """
    if status == "awaiting_review":
        return [
            ("brief", "Transactions", run_url(thread_id, "review")),
            ("questions", "Open questions", run_url(thread_id, "review", tab="questions")),
            ("history", "Earlier decisions", run_url(thread_id, "review", tab="history")),
            ("signoff", "Sign-off", run_url(thread_id, "review", tab="signoff")),
        ]
    return [("signed", "Sign-off record", run_url(thread_id, "signed"))]


def load_review(
    services: Services, thread: str, person: Person | None
) -> tuple[RunInfo, ReviewRequest, ReviewModel] | Response:
    """Read the run and its review request, or return the redirect that leads away from it.

    Args:
        services: The services.
        thread: The run.
        person: The person signed in, whose own held decisions the review counts; or None.

    Returns:
        The run, its request and the model of the review; or a redirect to the run page when the
        run is not waiting for a reviewer.

    Raises:
        HTTPException: 404, if the engine does not know the run.
    """
    info = read_run(services, thread)
    try:
        request = runs_of(services).review_request(thread)
    except NotAwaitingReviewError:
        return RedirectResponse(run_url(thread), status_code=303)
    except RunNotFoundError as exc:
        raise no_such_run(thread) from exc
    model = ReviewModel(
        request,
        services.drafts.get(thread, person),
        viewer=person,
        earlier=earlier_decisions(request),
    )
    return info, request, model


def history_table(request: Request, thread: str, review: ReviewRequest):
    """Build the table of what reviewers decided about the customer before."""
    rows = []
    for decision in review.history:
        tx_id = transaction_of(decision)
        what = "Question answered" if decision.outcome == "answer" else final_word(decision)
        rows.append(
            {
                "transaction": Cell(tx_id),
                "decision": Cell(what),
                "by": Cell(f"{decision.reviewer.name}, {decision.reviewer.role}"),
                "date": Cell(long_date(decision.date), sort_value=decision.date),
                "reason": Cell(decision.reason),
            }
        )
    sort = request.query_params.get("sort")
    descending = request.query_params.get("dir") == "desc"

    def href_for(**changes: str) -> str:
        query = {**dict(request.query_params), "tab": "history", **changes}
        return run_url(thread, "review") + "?" + urlencode(query)

    return build_table(
        HISTORY_COLUMNS,
        rows,
        sort=sort,
        descending=descending,
        href_for=href_for,
        export_href=run_url(thread, "history.csv"),
        caption=f"What reviewers decided about {review.customer.name} before",
        empty=f"No decision about {review.customer.name} has been recorded before.",
    )


def review_context(
    request: Request,
    services: Services,
    info: RunInfo,
    review: ReviewRequest,
    model: ReviewModel,
    *,
    tab: str,
    form_error: str | None = None,
    form_values: dict | None = None,
    error_target: str | None = None,
    chosen_tx: str | None = None,
) -> dict:
    """Build what the review page shows."""
    thread = info.thread_id
    rows = rows_of(info.state)
    by_tx = {c.fact.subject.anchor.partition(":")[2]: c for c in review.assessments}
    statement_of = {c.fact.id: s for s in review.statements for c in s.facts if c.needs_decision}
    selected = chosen_tx or request.query_params.get("tx")
    waiting = model.facts_waiting
    fallback = waiting[0] if waiting else next(iter(model.cited.values()), None)
    cited = by_tx.get(selected or "") or fallback
    view = view_state = next_href = raw_row = None
    if cited is not None and (
        selected in by_tx or selected not in {r["transaction_id"] for r in rows}
    ):
        view = assessment_view(statement_of[cited.fact.id], cited)
        view_state = model.fact_states[cited.fact.id]
        following = model.next_waiting(cited.fact.id)
        if following:
            next_tx = model.cited[following].fact.subject.anchor.partition(":")[2]
            next_href = run_url(thread, "review", tx=next_tx)
    elif selected:
        raw_row = next((r for r in rows if r["transaction_id"] == selected), None)
    current = view.tx_id if view else (raw_row or {}).get("transaction_id")
    shown = set(model.cited) | {q.id for q in review.open_questions}
    return {
        "page_title": "Review the brief",
        "answer": model.answer(),
        "model": model,
        "info": info,
        "tab": tab,
        "tabs_for": run_tabs(thread, info.status),
        "pic": review_picture(
            rows, review, model, href_for=lambda tx: run_url(thread, "review", tx=tx)
        ),
        "statements": statement_items(review, model),
        "unassessed": unassessed_items(
            review, model, rows, href=run_url(thread, "review", tab="questions")
        ),
        "view": view,
        "view_state": view_state,
        "raw_row": raw_row,
        "current_tx": current,
        "next_href": next_href,
        "no_assessment_words": NO_ASSESSMENT,
        "questions_href": run_url(thread, "review", tab="questions"),
        "tx_href": lambda tx: run_url(thread, "review", tx=tx),
        "history_table": history_table(request, thread, review),
        "thread": thread,
        "brief_digest": review.brief_digest,
        "form_error": form_error,
        "form_values": form_values or {},
        "error_target": error_target if error_target in shown else None,
        "sign_in": sign_in_address(request),
    }


def routes(services: Services) -> list[Route]:
    """Return the review page and the routes that record what the reviewer decides.

    The handlers are plain functions, which Starlette runs in its thread pool, because each one
    calls the run service. The routes that read a form read it first and then hand the rest to
    the pool.
    """

    def show(
        request: Request,
        *,
        tab: str | None = None,
        status: int = 200,
        chosen_tx: str | None = None,
        **problem,
    ) -> Response:
        thread = request.path_params["thread"]
        loaded = load_review(services, thread, current_person(request))
        if isinstance(loaded, Response):
            return loaded
        info, review, model = loaded
        chosen = tab or request.query_params.get("tab", "brief")
        chosen = chosen if chosen in TABS else "brief"
        context = review_context(
            request, services, info, review, model, tab=chosen, chosen_tx=chosen_tx, **problem
        )
        return render(request, "transaction_monitoring/review.html", context, status=status)

    def review_get(request: Request) -> Response:
        return show(request)

    def history_csv(request: Request) -> Response:
        loaded = load_review(services, request.path_params["thread"], current_person(request))
        if isinstance(loaded, Response):
            return loaded
        _, review, _ = loaded
        view = history_table(request, request.path_params["thread"], review)
        return PlainTextResponse(
            table_csv(view),
            media_type="text/csv",
            headers={"content-disposition": 'attachment; filename="earlier-decisions.csv"'},
        )

    def guarded(request: Request, action, tab: str, form) -> Response:
        """Run a recording action for a signed-in person on the brief they were shown."""
        thread = request.path_params["thread"]
        person = current_person(request)
        if person is None:
            return show(request, tab=tab, status=403, form_error=SIGN_IN_FIRST)
        loaded = load_review(services, thread, person)
        if isinstance(loaded, Response):
            return loaded
        info, brief_request, model = loaded
        if str(form.get("brief_digest", "")) != brief_request.brief_digest:
            return show(request, tab=tab, status=409, form_error=STALE)
        try:
            return action(info, brief_request, model, form, person)
        except ReviewInputError as exc:
            values = {k: str(v) for k, v in form.items()}
            target = values.get("fact_id") or values.get("question_id")
            tx = next(
                (
                    c.fact.subject.anchor.partition(":")[2]
                    for c in brief_request.assessments
                    if c.fact.id == values.get("fact_id")
                ),
                None,
            )
            return show(
                request,
                tab=tab,
                status=422,
                form_error=str(exc),
                form_values=values,
                error_target=target,
                chosen_tx=tx,
            )
        except ReviewMismatchError:
            return show(request, tab=tab, status=409, form_error=STALE)
        except ValidationError as exc:
            words = exc.errors()[0]["msg"]
            return show(
                request, tab=tab, status=422, form_error=f"That cannot be recorded: {words}."
            )
        except NotAwaitingReviewError:
            return RedirectResponse(run_url(thread), status_code=303)
        except RunNotFoundError as exc:
            raise no_such_run(thread) from exc
        except STATE_ERRORS as exc:
            raise state_unavailable(exc, "Nothing was recorded") from exc

    def recording(action, tab: str):
        """Make the route that reads a posted form and runs an action for the person."""

        async def endpoint(request: Request) -> Response:
            form = await request.form()
            return await run_in_threadpool(guarded, request, action, tab, form)

        return endpoint

    def decide(info, brief_request, model, form, person: Person) -> Response:
        decision = review_route.decide_assessment(
            brief_request,
            str(form.get("fact_id", "")),
            outcome=str(form.get("outcome", "")),
            reason=str(form.get("reason", "")),
            final=str(form.get("final", "")) or None,
            wording=str(form.get("wording", "")) or None,
            person=person,
            on=services.today(),
        )
        services.drafts.put_fact_decision(info.thread_id, decision)
        following = model.first_waiting(decision.subject_id) or decision.subject_id
        tx = model.cited[following].fact.subject.anchor.partition(":")[2]
        return RedirectResponse(run_url(info.thread_id, "review", tx=tx), status_code=303)

    def answer(info, brief_request, model, form, person: Person) -> Response:
        decision = review_route.answer_question(
            brief_request,
            str(form.get("question_id", "")),
            final=str(form.get("final", "")) or None,
            answer=str(form.get("answer", "")),
            reason=str(form.get("reason", "")),
            person=person,
            on=services.today(),
        )
        services.drafts.put_answer(info.thread_id, decision)
        return RedirectResponse(run_url(info.thread_id, "review", tab="questions"), status_code=303)

    def assume(info, brief_request, model, form, person: Person) -> Response:
        question_id = str(form.get("question_id", ""))
        words = review_route.check_assumption(
            brief_request, question_id, str(form.get("words", ""))
        )
        services.drafts.put_assumption(info.thread_id, person, question_id, words)
        return RedirectResponse(run_url(info.thread_id, "review", tab="questions"), status_code=303)

    def sign(info, brief_request, model, form, person: Person) -> Response:
        response = review_route.build_response(
            brief_request,
            model,
            services.drafts.get(info.thread_id, person),
            outcome=str(form.get("outcome", "")),
            reason=str(form.get("reason", "")) or None,
            person=person,
            on=services.today(),
        )
        runs = runs_of(services)
        status = runs.submit(info.thread_id, response)
        if status == "awaiting_review":
            # The engine refused the response on resume and left the run at the review.
            raise ReviewInputError(
                f"The brief was not recorded as {response.sign_off.outcome}. "
                + plain_error(runs.error(info.thread_id))
            )
        if status == "failed":
            return RedirectResponse(run_url(info.thread_id), status_code=303)
        try:
            services.drafts.clear(info.thread_id)
        except DraftFileError:  # the brief is signed; drafts left on a signed run are never shown
            LOG.exception(
                "Run %s is signed but its pending work could not be cleared", info.thread_id
            )
        return RedirectResponse(run_url(info.thread_id, "signed"), status_code=303)

    return [
        Route("/runs/{thread}/review", review_get, methods=["GET"]),
        Route("/runs/{thread}/history.csv", history_csv, methods=["GET"]),
        Route("/runs/{thread}/decide", recording(decide, "brief"), methods=["POST"]),
        Route("/runs/{thread}/answer", recording(answer, "questions"), methods=["POST"]),
        Route("/runs/{thread}/assume", recording(assume, "questions"), methods=["POST"]),
        Route("/runs/{thread}/sign", recording(sign, "signoff"), methods=["POST"]),
    ]


__all__ = ["PREFIX", "routes", "run_tabs"]
