"""The start page, the list of runs, and the page that shows a run while it is assessed."""

from __future__ import annotations

from urllib.parse import urlencode

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from context.errors import CustomerNotFoundError, EmptyStreamError
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
    customers,
    plain_error,
    read_run,
    run_url,
    runs_of,
    state_unavailable,
)
from review_app.pages import idle_marks, overview_picture, rows_of
from review_app.stream_picture import build_picture
from utils import db
from utils.transaction_processing import transaction_stream
from workflow.errors import InvalidRequestError
from workflow.requests import request_text
from workflow.runs import RunInProgressError

RUN_COLUMNS = (
    Column("run", "Run"),
    Column("transactions", "Transactions"),
    Column("status", "Status"),
    Column("reviewed", "Reviewed by"),
)
NOT_REVIEWED = "Not yet"
START_TEMPLATE = "transaction_monitoring/start.html"


def _plural(count: int, one: str) -> str:
    return f"{count} {one if count == 1 else one + 's'}"


def run_cells(info: RunInfo) -> dict[str, Cell]:
    """Return one run's table cells."""
    status = {"awaiting_review": "needs_person", "failed": "failed"}.get(info.status, "normal")
    held = info.state.get("sign_off")
    reviewed = NOT_REVIEWED
    if held:
        sign_off = SignOff.model_validate(held)
        reviewed = f"{sign_off.reviewer.name}, {sign_off.reviewer.role}, {long_date(sign_off.date)}"
    count = len(rows_of(info.state)) or None
    return {
        "run": Cell(
            info.label, href=run_url(info.thread_id), title=f"Open the run for {info.customer}"
        ),
        "transactions": Cell("" if count is None else str(count), sort_value=str(count or 0)),
        "status": Cell(STATUS_WORDS[info.status], status=status),  # type: ignore[arg-type]
        "reviewed": Cell(reviewed),
    }


def start_answer(infos: list[RunInfo]) -> Answer:
    """Build the start page's sentence and tiles from the runs."""
    count = len(infos)
    waiting = sum(i.status == "awaiting_review" for i in infos)
    signed = sum(i.status == "signed" for i in infos)
    if count == 0:
        sentence = "No customer has been assessed yet. Choose a customer to start."
    else:
        words = (
            ("awaiting_review", "waiting for a reviewer"),
            ("running", "being assessed"),
            ("signed", "signed"),
            ("returned", "returned"),
            ("failed", "stopped"),
        )
        parts = [f"{n} {word}" for key, word in words if (n := sum(i.status == key for i in infos))]
        sentence = f"{_plural(count, 'run')} so far: {', '.join(parts)}."
    return Answer(
        sentence=sentence,
        tiles=(
            Tile("Runs", str(count)),
            Tile("Waiting for a reviewer", str(waiting), "needs_person" if waiting else "normal"),
            Tile("Signed", str(signed)),
        ),
    )


def run_states(info: RunInfo, services: Services) -> dict[str, str]:
    """Say how each transaction a run covers stands, for the overview's marks.

    Args:
        info: The run.
        services: The services.

    Returns:
        For each transaction of the run, ``carried`` or ``needs`` for a run waiting for a reviewer
        (by what an earlier decision made of it), ``decided`` for a signed one, and ``idle`` for a
        run that is still being assessed, stopped or returned.
    """
    ids = [row["transaction_id"] for row in rows_of(info.state)]
    if info.status == "signed":
        return dict.fromkeys(ids, "decided")
    if info.status != "awaiting_review":
        return dict.fromkeys(ids, "idle")
    request = runs_of(services).review_request(info.thread_id)
    carried = {
        c.fact.subject.anchor.partition(":")[2]
        for c in request.assessments
        if c.carry.outcome == "carried"
    }
    return {tx: "carried" if tx in carried else "needs" for tx in ids}


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
            caption="Runs, newest first",
            empty="No customer has been assessed yet.",
        )

    def picture(found: list[RunInfo]):
        covering: dict[str, tuple[str, str]] = {}
        for info in found:  # newest first, so the first run to cover a transaction stands
            states = run_states(info, services)
            for tx_id, state in states.items():
                covering.setdefault(tx_id, (info.thread_id, state))
        rows = sorted(db.table("transactions"), key=lambda r: (r["timestamp"], r["transaction_id"]))
        return overview_picture(
            rows,
            covering,
            customers(),
            href_for=lambda thread, tx: run_url(thread, "review", tx=tx),
        )

    def start_page(
        request: Request,
        *,
        problem: str | None = None,
        status: int = 200,
        chosen: dict[str, str] | None = None,
    ):
        found = infos()
        context = {
            "page_title": "Transaction monitoring",
            "answer": start_answer(found),
            "table": table(request, found),
            "pic": picture(found),
            "customers": customers(),
            "chosen": chosen or {},
            "problem": problem,
            "sign_in": sign_in_address(request),
        }
        return render(request, START_TEMPLATE, context, status=status)

    def start_get(request: Request) -> Response:
        return start_page(request)

    def runs_csv(request: Request) -> Response:
        view = table(request, infos())
        return PlainTextResponse(
            table_csv(view),
            media_type="text/csv",
            headers={"content-disposition": 'attachment; filename="runs.csv"'},
        )

    def start_run(request: Request, form) -> Response:
        user_id = str(form.get("user_id", ""))
        start, end = str(form.get("start", "")) or None, str(form.get("end", "")) or None
        chosen = {"user_id": user_id, "start": start or "", "end": end or ""}
        if current_person(request) is None:
            return start_page(
                request,
                problem="Sign in with your name and role to start a run.",
                status=403,
                chosen=chosen,
            )
        if user_id not in {u for u, _ in customers()}:
            return start_page(request, problem="Choose a customer.", status=422, chosen=chosen)
        if start and end and start >= end:
            return start_page(
                request,
                problem="The day to start from must be before the day to stop at.",
                status=422,
                chosen=chosen,
            )
        payload = {"user_id": user_id, "request": request_text(user_id, start=start, end=end)}
        if start:
            payload["start"] = start
        if end:
            payload["end"] = end
        try:
            thread = runs_of(services).start(payload)  # type: ignore[arg-type]
        except RunInProgressError:
            return start_page(
                request,
                problem="A run is still being assessed. Start another when it has finished.",
                status=409,
                chosen=chosen,
            )
        except EmptyStreamError:
            return start_page(
                request,
                problem="That customer has no transaction in that window.",
                status=422,
                chosen=chosen,
            )
        except (InvalidRequestError, CustomerNotFoundError) as exc:
            return start_page(
                request, problem=f"The run could not be started. {exc}", status=422, chosen=chosen
            )
        except STATE_ERRORS as exc:
            raise state_unavailable(exc, "No run was started") from exc
        return RedirectResponse(run_url(thread), status_code=303)

    async def start_post(request: Request) -> Response:
        form = await request.form()
        return await run_in_threadpool(start_run, request, form)

    def run_page(request: Request) -> Response:
        thread = request.path_params["thread"]
        info = read_run(services, thread)
        if info.status == "awaiting_review":
            return RedirectResponse(run_url(thread, "review"), status_code=303)
        if info.status in {"signed", "returned"}:
            return RedirectResponse(run_url(thread, "signed"), status_code=303)
        return render(request, "transaction_monitoring/run.html", run_context(info, services))

    return [
        Route("/", start_get, methods=["GET"]),
        Route("/runs", start_post, methods=["POST"]),
        Route("/runs.csv", runs_csv),
        Route("/runs/{thread}", run_page),
    ]


def run_context(info: RunInfo, services: Services) -> dict:
    """Build what the run page shows while the run is assessed or after it stopped."""
    lanes = [(info.user_id, info.customer)]
    rows = transaction_stream(info.user_id, info.start, info.end)
    picture = build_picture(idle_marks(rows), lanes=lanes)
    if info.status == "failed":
        return {
            "page_title": "Run stopped",
            "answer": Answer(
                sentence=f"The run for {info.customer} stopped before it was finished."
            ),
            "info": info,
            "error": plain_error(runs_of(services).error(info.thread_id)),
            "pic": picture,
            "refresh": False,
        }
    return {
        "page_title": "Assessing the transactions",
        "answer": Answer(
            sentence=f"{info.customer}'s {_plural(len(rows), 'transaction')} are being assessed.",
            tiles=(Tile("Transactions", str(len(rows))),),
        ),
        "info": info,
        "error": None,
        "pic": picture,
        "refresh": True,
    }
