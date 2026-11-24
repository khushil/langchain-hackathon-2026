"""The start page, the list of runs, and the page that shows a run while it is being written."""

from __future__ import annotations

from urllib.parse import urlencode

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from fsi_common.app import Answer, Cell, Column, Tile, current_person, render, sign_in_address
from fsi_common.app.pages import build_table, table_csv
from review_app.context import PREFIX, STATUS_WORDS, RunInfo, Services, read_run, run_url, runs_of
from review_app.service import (
    DocumentNotFoundError,
    FirmNotFoundError,
    InvalidRequestError,
    RunInProgressError,
    UnknownSectionError,
)
from workflow.requests import brief_request_text

RUN_COLUMNS = (Column("brief", "Brief"), Column("sections", "Sections"), Column("status", "Status"))
START_TEMPLATE = "compliance_brief/start.html"


def _plural(count: int, one: str) -> str:
    return f"{count} {one if count == 1 else one + 's'}"


def run_cells(info: RunInfo) -> dict[str, Cell]:
    """Return one run's table cells."""
    status = {"awaiting_review": "needs_person", "failed": "failed"}.get(info.status, "normal")
    sections = ", ".join(info.sections) if info.sections else "All"
    return {
        "brief": Cell(
            info.label, href=run_url(info.thread_id), title=f"Open the brief for {info.firm_name}"
        ),
        "sections": Cell(sections, sort_value=sections),
        "status": Cell(STATUS_WORDS[info.status], status=status),  # type: ignore[arg-type]
    }


def start_answer(infos: list[RunInfo]) -> Answer:
    """Build the start page's sentence and tiles from the runs."""
    count = len(infos)
    waiting = sum(i.status == "awaiting_review" for i in infos)
    signed = sum(i.status == "signed" for i in infos)
    if count == 0:
        sentence = "No brief has been started. Choose a document and a firm to start one."
    else:
        words = (
            ("awaiting_review", "waiting for a reviewer"),
            ("running", "being written"),
            ("signed", "signed"),
            ("returned", "returned"),
            ("failed", "stopped"),
        )
        parts = [f"{n} {word}" for key, word in words if (n := sum(i.status == key for i in infos))]
        sentence = f"{_plural(count, 'brief')} so far: {', '.join(parts)}."
    return Answer(
        sentence=sentence,
        tiles=(
            Tile("Briefs", str(count)),
            Tile("Waiting for a reviewer", str(waiting), "needs_person" if waiting else "normal"),
            Tile("Signed", str(signed)),
        ),
    )


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
            caption="Briefs, newest first",
            empty="No brief has been started.",
        )

    def start_page(
        request: Request,
        *,
        problem: str | None = None,
        status: int = 200,
        ticked: list[str] | None = None,
    ):
        found = infos()
        library = services.library()
        context = {
            "page_title": "Compliance brief",
            "answer": start_answer(found),
            "table": table(request, found),
            "library": library,
            "problem": problem,
            "ticked": ticked,
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
            headers={"content-disposition": 'attachment; filename="briefs.csv"'},
        )

    def start_brief(request: Request, form) -> Response:
        chosen = [str(s) for s in form.getlist("sections")]
        person = current_person(request)
        if person is None:
            return start_page(
                request,
                problem="Sign in with your name and role to start a brief.",
                status=403,
                ticked=chosen,
            )
        library = services.library()
        document = library.document(str(form.get("document_id", "")))
        firm_id = str(form.get("firm_id", ""))
        if document is None or firm_id not in library.firms:
            return start_page(
                request, problem="Choose a document and a firm.", status=422, ticked=chosen
            )
        known = [s.number for s in document.sections]
        if not chosen or any(s not in known for s in chosen):
            return start_page(
                request, problem="Choose at least one section.", status=422, ticked=chosen
            )
        payload = {
            "document_id": document.document_id,
            "firm_id": firm_id,
            "request": brief_request_text(document.document_id, firm_id),
        }
        if sorted(chosen, key=known.index) != known:
            payload["sections"] = sorted(chosen, key=known.index)
        try:
            thread = runs_of(services).start(payload)
        except RunInProgressError:
            return start_page(
                request,
                problem="A brief is still being written. Start another when it has finished.",
                status=409,
                ticked=chosen,
            )
        except (
            InvalidRequestError,
            DocumentNotFoundError,
            FirmNotFoundError,
            UnknownSectionError,
        ) as exc:
            return start_page(
                request,
                problem=f"The brief could not be started. {exc}",
                status=422,
                ticked=chosen,
            )
        return RedirectResponse(run_url(thread), status_code=303)

    async def start_post(request: Request) -> Response:
        form = await request.form()
        return await run_in_threadpool(start_brief, request, form)

    def run_page(request: Request) -> Response:
        thread = request.path_params["thread"]
        info = read_run(services, thread)
        if info.status == "awaiting_review":
            return RedirectResponse(run_url(thread, "review"), status_code=303)
        if info.status in {"signed", "returned"}:
            return RedirectResponse(run_url(thread, "signed"), status_code=303)
        return render(request, "compliance_brief/run.html", run_context(info, services))

    return [
        Route("/", start_get, methods=["GET"]),
        Route("/runs", start_post, methods=["POST"]),
        Route("/runs.csv", runs_csv),
        Route("/runs/{thread}", run_page),
    ]


def run_context(info: RunInfo, services: Services) -> dict:
    """Build what the run page shows while the brief is written or after it stopped."""
    library = services.library()
    document = library.document(info.document_id)
    every = [s.number for s in document.sections] if document else []
    wanted = list(info.sections or every)
    titles = {s.number: s.title for s in document.sections} if document else {}
    read = set(info.state.get("section_results", {}))
    rows = [(n, titles.get(n, ""), n in read) for n in wanted]
    done = sum(r for _, _, r in rows)
    if info.status == "failed":
        error = runs_of(services).error(info.thread_id) or "The engine gave no reason."
        answer = Answer(sentence=f"The brief for {info.firm_name} stopped before it was finished.")
        return {
            "page_title": "Brief stopped",
            "answer": answer,
            "info": info,
            "error": error,
            "rows": rows,
            "refresh": False,
        }
    answer = Answer(
        sentence=f"The brief for {info.firm_name} is being written: {done} of {len(rows)} "
        f"{'section' if len(rows) == 1 else 'sections'} read.",
        tiles=(Tile("Sections read", f"{done} of {len(rows)}"),),
    )
    return {
        "page_title": "Writing the brief",
        "answer": answer,
        "info": info,
        "error": None,
        "rows": rows,
        "refresh": True,
    }
