"""The review page, where a named person reads the brief, opens each source and decides."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from fsi_common.app import current_person, render, sign_in_address
from fsi_common.records import Person, Source
from review_app import review_route
from review_app.context import RunInfo, Services, read_run, run_tabs, run_url, runs_of
from review_app.review_model import FactState, ReviewModel
from review_app.review_route import ReviewInputError
from review_app.service import NotAwaitingReviewError, RunNotFoundError
from review_app.source_view import anchor_label, mark_quote
from utils.state import CitedFact, ReviewMismatchError, ReviewRequest

TABS = ("brief", "questions", "signoff")
STALE = (
    "The brief changed after you opened it, so nothing was recorded. Read it again; decisions you "
    "made on facts that did not change are kept."
)
SIGN_IN_FIRST = "Sign in with your name and role before you decide on a brief."


@dataclass(frozen=True)
class SourcePanel:
    """The source of one selected fact, ready to show."""

    cited: CitedFact
    state: FactState
    place: str
    source_title: str
    digest: str
    segments: tuple | None
    next_href: str | None


def no_such_run(thread: str) -> HTTPException:
    """Return the error that says in words that the engine has no such run."""
    return HTTPException(404, f"There is no run {thread}.")


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
        firm_name=info.firm_name,
        document_title=info.document_title,
    )
    return info, request, model


def source_panel(info: RunInfo, model: ReviewModel, fact_id: str | None) -> SourcePanel | None:
    """Choose the fact whose source the panel shows and build the panel.

    Args:
        info: The run.
        model: The review.
        fact_id: The fact asked for in the address; the first fact waiting, else the first fact.

    Returns:
        The panel, or None when the brief cites no fact.
    """
    if not model.cited:
        return None
    waiting = model.facts_waiting
    chosen = model.cited.get(fact_id or "") or (
        waiting[0] if waiting else next(iter(model.cited.values()))
    )
    fact = chosen.fact
    sources = info.state.get("sources", {})
    held = sources.get(fact.subject.source_id)
    title = Source.model_validate(held).title if held else fact.subject.source_id
    following = model.next_waiting(fact.id)
    return SourcePanel(
        cited=chosen,
        state=model.fact_states[fact.id],
        place=anchor_label(fact.subject.anchor),
        source_title=title,
        digest=fact.provenance.as_of,
        segments=mark_quote(chosen.unit_text, fact.quote),
        next_href=run_url(info.thread_id, "review", fact=following) if following else None,
    )


def review_context(
    request: Request,
    services: Services,
    info: RunInfo,
    model: ReviewModel,
    *,
    tab: str,
    fact_id: str | None,
    form_error: str | None = None,
    form_values: dict | None = None,
    error_target: str | None = None,
) -> dict:
    """Build what the review page shows."""
    thread = info.thread_id
    selected = fact_id or request.query_params.get("fact")
    shown = set(model.cited) | {q.id for q in model.request.open_questions}
    error_target = error_target if error_target in shown else None
    return {
        "page_title": "Review the brief",
        "answer": model.answer(),
        "model": model,
        "info": info,
        "tab": tab,
        "tabs_for": run_tabs(thread, info.status),
        "panel": source_panel(info, model, selected) if tab == "brief" else None,
        "fact_href": lambda fid: run_url(thread, "review", fact=fid),
        "thread": thread,
        "brief_digest": model.request.brief_digest,
        "form_error": form_error,
        "form_values": form_values or {},
        "error_target": error_target,
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
        **problem,
    ) -> Response:
        thread = request.path_params["thread"]
        loaded = load_review(services, thread, current_person(request))
        if isinstance(loaded, Response):
            return loaded
        info, _, model = loaded
        chosen = tab or request.query_params.get("tab", "brief")
        chosen = chosen if chosen in TABS else "brief"
        context = review_context(
            request, services, info, model, tab=chosen, fact_id=None, **problem
        )
        return render(request, "compliance_brief/review.html", context, status=status)

    def review_get(request: Request) -> Response:
        return show(request)

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
            return show(
                request,
                tab=tab,
                status=422,
                form_error=str(exc),
                form_values=values,
                error_target=target,
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

    def recording(action, tab: str):
        """Make the route that reads a posted form and runs an action for the person."""

        async def endpoint(request: Request) -> Response:
            form = await request.form()
            return await run_in_threadpool(guarded, request, action, tab, form)

        return endpoint

    def decide(info, brief_request, model, form, person: Person) -> Response:
        decision = review_route.decide_fact(
            brief_request,
            str(form.get("fact_id", "")),
            outcome=str(form.get("outcome", "")),
            reason=str(form.get("reason", "")),
            amendment=str(form.get("amendment", "")) or None,
            person=person,
            on=services.today(),
        )
        services.drafts.put_fact_decision(info.thread_id, decision)
        following = model.next_waiting(decision.subject_id) or decision.subject_id
        return RedirectResponse(run_url(info.thread_id, "review", fact=following), status_code=303)

    def answer(info, brief_request, model, form, person: Person) -> Response:
        decision = review_route.answer_question(
            brief_request,
            str(form.get("question_id", "")),
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
        runs_of(services).submit(info.thread_id, response)
        services.drafts.clear(info.thread_id)
        return RedirectResponse(run_url(info.thread_id, "signed"), status_code=303)

    return [
        Route("/runs/{thread}/review", review_get, methods=["GET"]),
        Route("/runs/{thread}/decide", recording(decide, "brief"), methods=["POST"]),
        Route("/runs/{thread}/answer", recording(answer, "questions"), methods=["POST"]),
        Route("/runs/{thread}/assume", recording(assume, "questions"), methods=["POST"]),
        Route("/runs/{thread}/sign", recording(sign, "signoff"), methods=["POST"]),
    ]
