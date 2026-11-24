"""The facts table with its CSV export, and the page of a brief that has been signed or returned."""

from __future__ import annotations

from urllib.parse import urlencode

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from fsi_common.app import Answer, Cell, Column, Tile, current_person, render
from fsi_common.app.pages import build_table, table_csv
from fsi_common.app.rendering import long_date
from fsi_common.records import Decision, Fact, Person, SignOff
from review_app.context import RunInfo, Services, read_run, run_tabs, run_url
from review_app.routes_review import load_review
from review_app.source_view import (
    anchor_label,
    attribute_value,
    decision_line,
    kind_label,
    outcome_word,
    pick_decision,
    requirements_text,
)
from utils.records import FACT_CONTEXT

FACT_COLUMNS = (
    Column("paragraph", "Paragraph"),
    Column("kind", "Kind"),
    Column("requirement", "Requirement"),
    Column("deadline", "Deadline as written"),
    Column("checks", "Checks"),
    Column("decision", "Decision"),
)
DECISION_COLUMNS = (
    Column("about", "About"),
    Column("requirement", "Requirement"),
    Column("decision", "Decision"),
    Column("reviewer", "Reviewer"),
    Column("date", "Date"),
    Column("reason", "Reason"),
)


def _plural(count: int, one: str) -> str:
    return f"{count} {one if count == 1 else one + 's'}"


def fact_cells(fact: Fact, decision_text: str, status: str, href: str | None) -> dict[str, Cell]:
    """Return one fact's table cells."""
    failed = [c for c in fact.checks if c.outcome == "fail"]
    checks = f"{len(fact.checks) - len(failed)} of {len(fact.checks)} passed"
    return {
        "paragraph": Cell(
            anchor_label(fact.subject.anchor).replace("Paragraph ", ""),
            href=href,
            title=f"Open {anchor_label(fact.subject.anchor)} and its quoted words",
        ),
        "kind": Cell(kind_label(fact.kind)),
        "requirement": Cell(requirements_text(fact.attributes.get("requirement"))),
        "deadline": Cell(attribute_value(fact.attributes.get("deadline"))),
        "checks": Cell(checks, status="failed" if failed else "normal"),
        "decision": Cell(decision_text, status=status),  # type: ignore[arg-type]
    }


def decision_text(
    decision: Decision | None, viewer: Person | None, *, carried: bool, waiting: bool
) -> tuple[str, str]:
    """Say where a fact stands in a table cell and which status it carries.

    Args:
        decision: The decision that settles the fact, if there is one.
        viewer: The person signed in, or None; ``you`` is said only of their own decision.
        carried: Whether the decision was made in an earlier review.
        waiting: Whether the fact still needs a decision.

    Returns:
        The words and the status.
    """
    if waiting:
        return "Needs a person", "needs_person"
    if decision is None:
        return "No decision", "normal"
    words = decision_line(decision, viewer)
    return (f"{words}, carried from an earlier review" if carried else words), "normal"


def _records(info: RunInfo, key: str) -> dict:
    return info.state.get(key, {}) or {}


def _decisions_by_subject(info: RunInfo) -> dict[str, Decision]:
    """Return the decision each fact or question of a finished brief stands on, one for each."""
    grouped: dict[str, list[Decision]] = {}
    for raw in _records(info, "decisions").values():
        decision = Decision.model_validate(raw)
        grouped.setdefault(decision.subject_id, []).append(decision)
    held = info.state.get("sign_off")
    sign_off = SignOff.model_validate(held) if held else None
    return {sid: pick_decision(found, sign_off) for sid, found in grouped.items()}  # type: ignore[misc]


def signed_facts(info: RunInfo) -> list[tuple[Fact, Decision | None]]:
    """Return the facts a finished brief cites, each with the decision it stands on."""
    brief = info.state.get("draft_brief") or {}
    cited = [fid for s in brief.get("statements", []) for fid in s["cites"]]
    decisions = _decisions_by_subject(info)
    facts = _records(info, "facts")
    return [
        (Fact.model_validate(facts[fid][0], context=FACT_CONTEXT), decisions.get(fid))
        for fid in dict.fromkeys(cited)
        if fid in facts
    ]


def routes(services: Services) -> list[Route]:
    """Return the facts and signed pages' routes, bound to the services."""

    def fact_table(request: Request, info: RunInfo):
        viewer = current_person(request)
        loaded = load_review(services, info.thread_id, viewer)
        rows, decided, failed = [], 0, 0
        if isinstance(loaded, Response):
            for fact, decision in signed_facts(info):
                text, status = decision_text(decision, viewer, carried=False, waiting=False)
                rows.append(fact_cells(fact, text, status, None))
                decided += decision is not None
                failed += not fact.passed_checks
            total = len(rows)
        else:
            _, _, model = loaded
            for fid, cited in model.cited.items():
                state = model.fact_states[fid]
                text, status = decision_text(
                    state.decision,
                    viewer,
                    carried=state.kind == "carried",
                    waiting=not state.settled,
                )
                rows.append(
                    fact_cells(
                        cited.fact, text, status, run_url(info.thread_id, "review", fact=fid)
                    )
                )
                decided += state.settled
                failed += not cited.fact.passed_checks
            total = len(rows)
        sort = request.query_params.get("sort")
        descending = request.query_params.get("dir") == "desc"

        def href_for(**changes: str) -> str:
            return (
                run_url(info.thread_id, "facts")
                + "?"
                + urlencode({**dict(request.query_params), **changes})
            )

        export = run_url(info.thread_id, "facts.csv") + (
            "?" + urlencode({"sort": sort, "dir": "desc" if descending else "asc"}) if sort else ""
        )
        view = build_table(
            FACT_COLUMNS,
            rows,
            sort=sort,
            descending=descending,
            href_for=href_for,
            export_href=export,
            caption="Facts the brief cites",
            empty="The brief cites no facts.",
        )
        return view, total, decided, failed

    def info_for(request: Request) -> RunInfo:
        info = read_run(services, request.path_params["thread"])
        if info.status in {"running", "failed"}:
            raise HTTPException(404, "The brief has no facts to show yet.")
        return info

    def facts_page(request: Request) -> Response:
        info = info_for(request)
        view, total, decided, failed = fact_table(request, info)
        waiting = total - decided
        sentence = f"{_plural(total, 'fact')} support the brief for {info.firm_name}; " + (
            f"{waiting} still need a decision." if waiting else "every one has a decision."
        )
        answer = Answer(
            sentence=sentence,
            tiles=(
                Tile("Facts", str(total)),
                Tile("Decided", f"{decided} of {total}", "needs_person" if waiting else "normal"),
                Tile("Failed checks", str(failed), "failed" if failed else "normal"),
            ),
        )
        context = {
            "page_title": "Facts",
            "answer": answer,
            "table": view,
            "info": info,
            "tabs_for": run_tabs(info.thread_id, info.status),
            "thread": info.thread_id,
        }
        return render(request, "compliance_brief/facts.html", context)

    def facts_csv(request: Request) -> Response:
        info = info_for(request)
        view, *_ = fact_table(request, info)
        return PlainTextResponse(
            table_csv(view),
            media_type="text/csv",
            headers={"content-disposition": 'attachment; filename="facts.csv"'},
        )

    def decisions_csv(request: Request) -> Response:
        info = read_run(services, request.path_params["thread"])
        if info.status not in {"signed", "returned"}:
            raise HTTPException(404, "The brief has no decisions to export yet.")
        view, _ = decisions_view(request, info)
        return PlainTextResponse(
            table_csv(view),
            media_type="text/csv",
            headers={"content-disposition": 'attachment; filename="decisions.csv"'},
        )

    def signed_page(request: Request) -> Response:
        info = read_run(services, request.path_params["thread"])
        if info.status == "awaiting_review":
            return RedirectResponse(run_url(info.thread_id, "review"), status_code=303)
        if info.status not in {"signed", "returned"}:
            return RedirectResponse(run_url(info.thread_id), status_code=303)
        return render(request, "compliance_brief/signed.html", signed_context(request, info))

    return [
        Route("/runs/{thread}/facts", facts_page),
        Route("/runs/{thread}/facts.csv", facts_csv),
        Route("/runs/{thread}/decisions.csv", decisions_csv),
        Route("/runs/{thread}/signed", signed_page),
    ]


def decisions_view(request: Request, info: RunInfo):
    """Return the table of the decisions a finished brief stands on, one for each subject."""
    brief = info.state.get("draft_brief") or {}
    facts = {fid: contents[0] for fid, contents in _records(info, "facts").items()}
    questions = _records(info, "open_questions")
    cited = {fid for s in brief.get("statements", []) for fid in s["cites"]}
    wanted = cited | set(brief.get("open_question_ids", []))
    rows = []
    for subject_id, decision in _decisions_by_subject(info).items():
        if subject_id not in wanted:
            continue
        if subject_id in facts:
            about = anchor_label(facts[subject_id]["subject"]["anchor"])
            requirement = requirements_text(facts[subject_id]["attributes"].get("requirement"))
        else:
            about = questions.get(subject_id, {}).get("question", subject_id)
            requirement = ""
        what = decision.answer or decision.amendment or ""
        rows.append(
            {
                "about": Cell(about),
                "requirement": Cell(requirement),
                "decision": Cell(outcome_word(decision) + (f": {what}" if what else "")),
                "reviewer": Cell(f"{decision.reviewer.name}, {decision.reviewer.role}"),
                "date": Cell(long_date(decision.date), sort_value=decision.date),
                "reason": Cell(decision.reason),
            }
        )
    sort = request.query_params.get("sort")
    descending = request.query_params.get("dir") == "desc"

    def href_for(**changes: str) -> str:
        return (
            run_url(info.thread_id, "signed")
            + "?"
            + urlencode({**dict(request.query_params), **changes})
        )

    view = build_table(
        DECISION_COLUMNS,
        rows,
        sort=sort,
        descending=descending,
        href_for=href_for,
        export_href=run_url(info.thread_id, "decisions.csv")
        + ("?" + urlencode({"sort": sort, "dir": "desc" if descending else "asc"}) if sort else ""),
        caption="Decisions made on the brief",
        empty="No decisions were recorded.",
    )
    return view, len(rows)


def signed_context(request: Request, info: RunInfo) -> dict:
    """Build what the page of a signed or returned brief shows."""
    sign_off = SignOff.model_validate(info.state["sign_off"])
    brief = info.state.get("draft_brief") or {}
    view, decisions = decisions_view(request, info)
    word = "signed" if sign_off.outcome == "signed" else "returned"
    who = f"{sign_off.reviewer.name}, {sign_off.reviewer.role}"
    sentence = f"{who}, {word} the brief for {info.firm_name}."
    answer = Answer(
        sentence=sentence,
        tiles=(
            Tile("Statements", str(len(brief.get("statements", [])))),
            Tile("Decisions recorded", str(decisions)),
            Tile("Assumptions accepted", str(len(sign_off.assumptions))),
        ),
    )
    return {
        "page_title": f"Brief {word}",
        "answer": answer,
        "sign_off": sign_off,
        "table": view,
        "info": info,
        "tabs_for": run_tabs(info.thread_id, info.status),
        "thread": info.thread_id,
    }
