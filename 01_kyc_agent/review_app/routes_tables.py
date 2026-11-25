"""The screenings table, the CSV exports, and the page of a batch signed or returned."""

from __future__ import annotations

from urllib.parse import urlencode

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from fsi_common.app import Answer, Cell, Column, Tile, current_person, render
from fsi_common.app.pages import build_table, table_csv
from fsi_common.app.rendering import long_date
from fsi_common.records import Decision, SignOff
from review_app.context import RunInfo, Services, read_run, run_tabs, run_url
from review_app.picture import Picture
from review_app.reviewing import (
    application_rows,
    load_review,
    picture_of,
    signed_decisions,
)
from review_app.routes_review import batch_table, waiting_questions
from review_app.run_data import read_run_data
from review_app.wording import outcome_word, proposal_words

SCREENING_COLUMNS = (
    Column("application", "Application"),
    Column("entry", "Entry"),
    Column("list", "List"),
    Column("result", "Result"),
    Column("detail", "What was found"),
)
DECISION_COLUMNS = (
    Column("about", "About"),
    Column("decision", "Decision"),
    Column("reviewer", "Reviewer"),
    Column("date", "Date"),
    Column("reason", "Reason"),
)


def _plural(count: int, one: str) -> str:
    return f"{count} {one if count == 1 else one + 's'}"


def screening_rows(picture: Picture, thread: str) -> list[dict[str, Cell]]:
    """Return one table row for each screening of the picture, in application order."""
    rows = []
    for row in picture.rows:
        for cell, entry in zip(row.cells, picture.entries, strict=True):
            status = "needs_person" if cell.state in {"needs", "near"} else "normal"
            if cell.state == "not_screened":
                status = "failed"
            rows.append(
                {
                    "application": Cell(
                        row.customer_id, href=row.href, title=f"Open {row.customer_id}"
                    ),
                    "entry": Cell(entry.name, sort_value=f"{entry.number:02d}"),
                    "list": Cell(entry.list_label),
                    "result": Cell(cell.word, status=status),  # type: ignore[arg-type]
                    "detail": Cell(cell.detail),
                }
            )
    return rows


def decisions_rows(info: RunInfo) -> list[dict[str, Cell]]:
    """Return the table of the decisions a finished batch stands on, one for each subject."""
    data = read_run_data(info.state)
    rows = []
    for subject, decision in signed_decisions(info).items():
        fact = data.facts.get(subject)
        if fact is not None:
            about = f"{fact.subject.anchor.partition(':')[2]}: {proposal_words(fact)}"
        else:
            about = data.questions[subject].question if subject in data.questions else subject
        what = decision.answer or decision.amendment or ""
        rows.append(_decision_row(about, decision, what))
    return sorted(rows, key=lambda r: r["about"].text)


def _decision_row(about: str, decision: Decision, what: str) -> dict[str, Cell]:
    return {
        "about": Cell(about),
        "decision": Cell(outcome_word(decision) + (f": {what}" if what else "")),
        "reviewer": Cell(f"{decision.reviewer.name}, {decision.reviewer.role}"),
        "date": Cell(long_date(decision.date), sort_value=decision.date),
        "reason": Cell(decision.reason),
    }


def routes(services: Services) -> list[Route]:
    """Return the screenings, export and signed pages' routes, bound to the services."""

    def finished_or_waiting(request: Request) -> RunInfo:
        info = read_run(services, request.path_params["thread"])
        if info.status in {"running", "failed"}:
            raise HTTPException(404, "The batch has nothing to show yet.")
        return info

    def settled_for(request: Request, info: RunInfo):
        """Return the picture's settled questions, and the review model when one is waiting."""
        if info.status == "awaiting_review":
            loaded = load_review(services, info.thread_id, current_person(request))
            if not isinstance(loaded, Response):
                return loaded[2].settled_questions(), loaded[2]
        found = {}
        for subject, d in signed_decisions(info).items():
            if subject.startswith("question:"):
                found[subject] = f"Answered by {d.reviewer.name}, on {long_date(d.date)}"
        for assumption in (info.state.get("sign_off") or {}).get("assumptions", []):
            found[assumption["question_id"]] = "Accepted as an assumption"
        return found, None

    def screenings_table(request: Request, info: RunInfo):
        settled, _ = settled_for(request, info)
        picture = picture_of(info, settled)
        sort = request.query_params.get("sort")
        descending = request.query_params.get("dir") == "desc"

        def href_for(**changes: str) -> str:
            return (
                run_url(info.thread_id, "screenings")
                + "?"
                + urlencode({**dict(request.query_params), **changes})
            )

        view = build_table(
            SCREENING_COLUMNS,
            screening_rows(picture, info.thread_id),
            sort=sort,
            descending=descending,
            href_for=href_for,
            export_href=run_url(info.thread_id, "screenings.csv")
            + (f"?sort={sort}&dir={'desc' if descending else 'asc'}" if sort else ""),
            caption="Every application against every list entry",
            empty="The batch holds no screening.",
        )
        return view, picture

    def screenings_page(request: Request) -> Response:
        info = finished_or_waiting(request)
        view, picture = screenings_table(request, info)
        needs = sum(c.state in {"needs", "near"} for r in picture.rows for c in r.cells)
        answer = Answer(
            sentence=f"{picture.total} screenings of {_plural(len(picture.rows), 'application')} "
            f"against {len(picture.entries)} list entries: "
            f"{picture.with_facts} kept as facts and {picture.without_facts} with no likeness.",
            tiles=(
                Tile("Screenings", str(picture.total)),
                Tile("Kept as facts", str(picture.with_facts)),
                Tile("Waiting for a person", str(needs), "needs_person" if needs else "normal"),
            ),
        )
        context = {
            "page_title": "Screenings",
            "answer": answer,
            "table": view,
            "tabs_for": run_tabs(info.thread_id, info.status),
        }
        return render(request, "kyc/screenings.html", context)

    def screenings_csv(request: Request) -> Response:
        info = finished_or_waiting(request)
        return PlainTextResponse(
            table_csv(screenings_table(request, info)[0]),
            media_type="text/csv",
            headers={"content-disposition": 'attachment; filename="screenings.csv"'},
        )

    def applications_csv(request: Request) -> Response:
        info = finished_or_waiting(request)
        _, model = settled_for(request, info)
        data = read_run_data(info.state)
        proposals = {f: x for f, x in data.facts.items() if x.kind == "proposal"}
        waiting = waiting_questions(model) if model else {}
        rows = application_rows(info, proposals, waiting, model, current_person(request))
        return PlainTextResponse(
            table_csv(batch_table(request, info, rows)),
            media_type="text/csv",
            headers={"content-disposition": 'attachment; filename="applications.csv"'},
        )

    def decisions_csv(request: Request) -> Response:
        info = read_run(services, request.path_params["thread"])
        if info.status not in {"signed", "returned"}:
            raise HTTPException(404, "The batch has no decisions to export yet.")
        view = _decisions_view(request, info)
        return PlainTextResponse(
            table_csv(view),
            media_type="text/csv",
            headers={"content-disposition": 'attachment; filename="decisions.csv"'},
        )

    def _decisions_view(request: Request, info: RunInfo):
        sort = request.query_params.get("sort")
        descending = request.query_params.get("dir") == "desc"

        def href_for(**changes: str) -> str:
            return (
                run_url(info.thread_id, "signed")
                + "?"
                + urlencode({**dict(request.query_params), **changes})
            )

        return build_table(
            DECISION_COLUMNS,
            decisions_rows(info),
            sort=sort,
            descending=descending,
            href_for=href_for,
            export_href=run_url(info.thread_id, "decisions.csv")
            + (f"?sort={sort}&dir={'desc' if descending else 'asc'}" if sort else ""),
            caption="Decisions made on the batch",
            empty="No decisions were recorded.",
        )

    def signed_page(request: Request) -> Response:
        info = read_run(services, request.path_params["thread"])
        if info.status == "awaiting_review":
            return RedirectResponse(run_url(info.thread_id, "review"), status_code=303)
        if info.status not in {"signed", "returned"}:
            return RedirectResponse(run_url(info.thread_id), status_code=303)
        sign_off = SignOff.model_validate(info.state["sign_off"])
        view = _decisions_view(request, info)
        settled, _ = settled_for(request, info)
        picture = picture_of(info, settled)
        word = "signed" if sign_off.outcome == "signed" else "returned"
        answer = Answer(
            sentence=f"{sign_off.reviewer.name}, {sign_off.reviewer.role}, {word} the batch of "
            f"{_plural(len(picture.rows), 'application')}.",
            tiles=(
                Tile("Applications", str(len(picture.rows))),
                Tile("Decisions recorded", str(len(view.rows))),
                Tile("Assumptions accepted", str(len(sign_off.assumptions))),
            ),
        )
        context = {
            "page_title": f"Batch {word}",
            "answer": answer,
            "sign_off": sign_off,
            "picture": picture,
            "table": view,
            "tabs_for": run_tabs(info.thread_id, info.status),
        }
        return render(request, "kyc/signed.html", context)

    return [
        Route("/runs/{thread}/screenings", screenings_page),
        Route("/runs/{thread}/screenings.csv", screenings_csv),
        Route("/runs/{thread}/applications.csv", applications_csv),
        Route("/runs/{thread}/decisions.csv", decisions_csv),
        Route("/runs/{thread}/signed", signed_page),
    ]
