"""The start page, the list of batches, and the page that shows a batch while it is being read."""

from __future__ import annotations

from urllib.parse import urlencode

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from context.reader import read_applications
from fsi_common.app import Answer, Cell, Column, Tile, current_person, render, sign_in_address
from fsi_common.app.pages import build_table, table_csv
from fsi_common.app.rendering import long_date
from fsi_common.records import SignOff
from review_app.context import (
    PREFIX,
    STATE_ERRORS,
    STATUS_WORDS,
    RunInfo,
    Services,
    plain_error,
    read_run,
    run_url,
    runs_of,
    state_unavailable,
)
from review_app.service import ApplicationNotFoundError, InvalidRequestError, RunInProgressError
from workflow.requests import request_text

RUN_COLUMNS = (
    Column("batch", "Batch"),
    Column("status", "Status"),
    Column("reviewed", "Reviewed by"),
)
NOT_REVIEWED = "Not yet"


def _plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else many or one + 's'}"


def run_cells(info: RunInfo) -> dict[str, Cell]:
    """Return one run's table cells."""
    status = {"awaiting_review": "needs_person", "failed": "failed"}.get(info.status, "normal")
    held = info.state.get("sign_off")
    reviewed = NOT_REVIEWED
    if held:
        sign_off = SignOff.model_validate(held)
        reviewed = f"{sign_off.reviewer.name}, {sign_off.reviewer.role}, {long_date(sign_off.date)}"
    return {
        "batch": Cell(info.label, href=run_url(info.thread_id), title="Open this batch"),
        "status": Cell(STATUS_WORDS[info.status], status=status),  # type: ignore[arg-type]
        "reviewed": Cell(reviewed),
    }


def start_answer(infos: list[RunInfo]) -> Answer:
    """Build the start page's sentence and tiles from the runs."""
    count = len(infos)
    waiting = sum(i.status == "awaiting_review" for i in infos)
    signed = sum(i.status == "signed" for i in infos)
    if count == 0:
        sentence = "No batch has been started. Choose applications to read and screen."
    else:
        words = (
            ("awaiting_review", "waiting for a reviewer"),
            ("running", "being read"),
            ("signed", "signed"),
            ("returned", "returned"),
            ("failed", "stopped"),
        )
        parts = [f"{n} {word}" for key, word in words if (n := sum(i.status == key for i in infos))]
        sentence = f"{_plural(count, 'batch', 'batches')} so far: {', '.join(parts)}."
    return Answer(
        sentence=sentence,
        tiles=(
            Tile("Batches", str(count)),
            Tile("Waiting for a reviewer", str(waiting), "needs_person" if waiting else "normal"),
            Tile("Signed", str(signed)),
        ),
    )


def run_context(info: RunInfo, services: Services) -> dict:
    """Build what the run page shows while the batch is read or after it stopped."""
    state = info.state
    read = len(state.get("raw_reads", {}))
    asked = len(info.customers)
    if info.status == "failed":
        return {
            "page_title": "Batch stopped",
            "answer": Answer(sentence="The batch stopped before it was finished."),
            "error": plain_error(runs_of(services).error(info.thread_id)),
            "refresh": False,
            "progress": "",
        }
    return {
        "page_title": "Reading the batch",
        "answer": Answer(
            sentence=f"The batch is being read: {read} of {asked} "
            f"{'application' if asked == 1 else 'applications'} read.",
            tiles=(Tile("Applications read", f"{read} of {asked}"),),
        ),
        "error": None,
        "refresh": True,
        "progress": f"{read} of {asked} applications read so far.",
    }


def routes(services: Services) -> list[Route]:
    """Return the start and run routes, bound to the services."""

    def infos() -> list[RunInfo]:
        runs = runs_of(services)
        return [read_run(services, t) for t in runs.list_runs()]

    def table(request: Request, found: list[RunInfo]):
        sort = request.query_params.get("sort")
        descending = request.query_params.get("dir") == "desc"

        def href_for(**changes: str) -> str:
            return f"{PREFIX}/?" + urlencode({**dict(request.query_params), **changes})

        return build_table(
            RUN_COLUMNS,
            [run_cells(i) for i in found],
            sort=sort,
            descending=descending,
            href_for=href_for,
            export_href=f"{PREFIX}/runs.csv"
            + (f"?sort={sort}&dir={'desc' if descending else 'asc'}" if sort else ""),
            caption="Batches, newest first",
            empty="No batch has been started.",
        )

    def start_page(
        request: Request, *, problem: str | None = None, status: int = 200, ticked=None
    ) -> Response:
        found = infos()
        customers = [u.anchor.partition(":")[2] for u in read_applications().units]
        context = {
            "page_title": "KYC onboarding",
            "answer": start_answer(found),
            "table": table(request, found),
            "customers": customers,
            "problem": problem,
            "ticked": ticked,
            "sign_in": sign_in_address(request),
        }
        return render(request, "kyc/start.html", context, status=status)

    def runs_csv(request: Request) -> Response:
        return PlainTextResponse(
            table_csv(table(request, infos())),
            media_type="text/csv",
            headers={"content-disposition": 'attachment; filename="batches.csv"'},
        )

    def start_batch(request: Request, form) -> Response:
        chosen = [str(c) for c in form.getlist("customers")]
        if current_person(request) is None:
            return start_page(
                request,
                problem="Sign in with your name and role to start a batch.",
                status=403,
                ticked=chosen,
            )
        if not chosen:
            return start_page(
                request, problem="Choose at least one application.", status=422, ticked=chosen
            )
        payload = {"request": request_text(len(chosen)), "customer_ids": chosen}
        try:
            thread = runs_of(services).start(payload)
        except RunInProgressError:
            return start_page(
                request,
                problem="A batch is still being read. Start another when it has finished.",
                status=409,
                ticked=chosen,
            )
        except (InvalidRequestError, ApplicationNotFoundError) as exc:
            return start_page(
                request,
                problem=f"The batch could not be started. {exc}",
                status=422,
                ticked=chosen,
            )
        except STATE_ERRORS as exc:
            raise state_unavailable(exc, "No batch was started") from exc
        return RedirectResponse(run_url(thread), status_code=303)

    async def start_post(request: Request) -> Response:
        form = await request.form()
        return await run_in_threadpool(start_batch, request, form)

    def run_page(request: Request) -> Response:
        thread = request.path_params["thread"]
        info = read_run(services, thread)
        if info.status == "awaiting_review":
            return RedirectResponse(run_url(thread, "review"), status_code=303)
        if info.status in {"signed", "returned"}:
            return RedirectResponse(run_url(thread, "signed"), status_code=303)
        return render(request, "kyc/run.html", run_context(info, services))

    return [
        Route("/", lambda request: start_page(request), methods=["GET"]),
        Route("/runs", start_post, methods=["POST"]),
        Route("/runs.csv", runs_csv),
        Route("/runs/{thread}", run_page),
    ]
