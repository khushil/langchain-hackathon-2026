"""The routes that record what the reviewer decides: a decision, an answer, a sign-off."""

from __future__ import annotations

import logging
from collections.abc import Callable

from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from fsi_common.app import current_person
from fsi_common.records import Person
from review_app import review_route
from review_app.context import (
    STATE_ERRORS,
    Services,
    plain_error,
    run_url,
    runs_of,
    state_unavailable,
)
from review_app.drafts import DraftFileError
from review_app.review_route import ReviewInputError
from review_app.reviewing import load_review
from review_app.routes_review import ReviewPages, next_to_decide
from review_app.service import NotAwaitingReviewError, RunNotFoundError
from utils.kyc_state import ReviewMismatchError

LOG = logging.getLogger("review_app.routes_record")
STALE = (
    "The batch changed after you opened it, so nothing was recorded. Read it again; decisions "
    "you made on proposals that did not change are kept."
)
SIGN_IN_FIRST = "Sign in with your name and role before you decide on a batch."


def routes(services: Services, pages: ReviewPages) -> list[Route]:
    """Return the recording routes, bound to the services and to the pages they redraw."""

    def where(request: Request, form, *, status: int, **problem) -> Response:
        """Draw the page the form came from, with what the person typed kept."""
        customer = str(form.get("customer", ""))
        request.path_params["customer"] = customer
        if customer:
            return pages.application(request, status=status, **problem)
        if request.url.path.endswith("/sign"):
            return pages.signoff(request, status=status, **problem)
        return pages.batch(request, status=status, **problem)

    def guarded(request: Request, action: Callable, form) -> Response:
        thread = request.path_params["thread"]
        person = current_person(request)
        if person is None:
            return where(request, form, status=403, form_error=SIGN_IN_FIRST)
        loaded = load_review(services, thread, person)
        if isinstance(loaded, Response):
            return loaded
        info, batch_request, model = loaded
        if str(form.get("brief_digest", "")) != batch_request.brief_digest:
            return where(request, form, status=409, form_error=STALE)
        try:
            return action(info, batch_request, model, form, person)
        except ReviewInputError as exc:
            values = {k: str(v) for k, v in form.items()}
            target = values.get("fact_id") or values.get("question_id")
            return where(
                request, form, status=422, form_error=str(exc), form_values=values,
                error_target=target,
            )  # fmt: skip
        except ReviewMismatchError:
            return where(request, form, status=409, form_error=STALE)
        except ValidationError as exc:
            words = exc.errors()[0]["msg"]
            return where(request, form, status=422, form_error=f"That cannot be recorded: {words}.")
        except NotAwaitingReviewError:
            return RedirectResponse(run_url(thread), status_code=303)
        except RunNotFoundError as exc:
            raise HTTPException(404, f"There is no run {thread}.") from exc
        except STATE_ERRORS as exc:
            raise state_unavailable(exc, "Nothing was recorded") from exc

    def recording(action: Callable):
        async def endpoint(request: Request) -> Response:
            form = await request.form()
            return await run_in_threadpool(guarded, request, action, form)

        return endpoint

    def back(info, model, customer: str) -> Response:
        following = next_to_decide(model, customer) if customer else None
        target = run_url(info.thread_id, "applications", following) if following else None
        return RedirectResponse(target or run_url(info.thread_id, "review"), status_code=303)

    def decide(info, request, model, form, person: Person) -> Response:
        decision = review_route.decide_proposal(
            request,
            str(form.get("fact_id", "")),
            outcome=str(form.get("outcome", "")),
            reason=str(form.get("reason", "")),
            amendment=str(form.get("amendment", "")) or None,
            person=person,
            on=services.today(),
        )
        services.drafts.put_fact_decision(info.thread_id, decision)
        return back(info, model, str(form.get("customer", "")))

    def stay(info, customer: str) -> Response:
        return RedirectResponse(run_url(info.thread_id, "applications", customer), status_code=303)

    def answer(info, request, model, form, person: Person) -> Response:
        decision = review_route.answer_question(
            request,
            str(form.get("question_id", "")),
            answer=str(form.get("answer", "")),
            reason=str(form.get("reason", "")),
            person=person,
            on=services.today(),
        )
        services.drafts.put_answer(info.thread_id, decision)
        return (
            stay(info, str(form.get("customer", "")))
            if form.get("customer")
            else back(info, model, "")
        )

    def assume(info, request, model, form, person: Person) -> Response:
        question_id = str(form.get("question_id", ""))
        words = review_route.check_assumption(request, question_id, str(form.get("words", "")))
        services.drafts.put_assumption(info.thread_id, person, question_id, words)
        return (
            stay(info, str(form.get("customer", "")))
            if form.get("customer")
            else back(info, model, "")
        )

    def sign(info, request, model, form, person: Person) -> Response:
        response = review_route.build_response(
            request,
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
            raise ReviewInputError(
                f"The batch was not recorded as {response.sign_off.outcome}. "
                + plain_error(runs.error(info.thread_id))
            )
        if status == "failed":
            return RedirectResponse(run_url(info.thread_id), status_code=303)
        try:
            services.drafts.clear(info.thread_id)
        except DraftFileError:  # the batch is signed; drafts left on a signed run are never shown
            LOG.exception(
                "Run %s is signed but its pending work could not be cleared", info.thread_id
            )
        return RedirectResponse(run_url(info.thread_id, "signed"), status_code=303)

    return [
        Route("/runs/{thread}/decide", recording(decide), methods=["POST"]),
        Route("/runs/{thread}/answer", recording(answer), methods=["POST"]),
        Route("/runs/{thread}/assume", recording(assume), methods=["POST"]),
        Route("/runs/{thread}/sign", recording(sign), methods=["POST"]),
    ]
