"""The page of a brief a person has signed or returned: the record, the decisions and the stream."""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from fsi_common.app import Answer, Cell, Column, Tile, render
from fsi_common.app.pages import build_table, table_csv
from fsi_common.app.rendering import long_date
from fsi_common.records import Decision, OpenQuestion, SignOff
from review_app.context import RunInfo, Services, read_run, run_url
from review_app.pages import finished_picture, rows_of
from review_app.routes_review import no_such_run, run_tabs
from review_app.views import assessment_view, final_word, pick_decision
from workflow.review import build_review_request

DECISION_COLUMNS = (
    Column("transaction", "Transaction"),
    Column("proposed", "Proposed"),
    Column("decision", "Decision"),
    Column("by", "Made by"),
    Column("date", "Date"),
    Column("reason", "Reason"),
)


def _plural(count: int, one: str) -> str:
    return f"{count} {one if count == 1 else one + 's'}"


def finished(info: RunInfo, services: Services):
    """Rebuild what a finished brief showed from the state it ended in.

    Args:
        info: The run, signed or returned.
        services: The services.

    Returns:
        The review request as it was, the sign-off, the decision that stands on each assessment by
        transaction, and the decisions made about each question by question id.
    """
    state = info.state
    sign_off = SignOff.model_validate(state["sign_off"])
    review = build_review_request(state, {})
    held = [Decision.model_validate(d) for d in state.get("decisions", {}).values()]
    by_subject: dict[str, list[Decision]] = defaultdict(list)
    for decision in held:
        by_subject[decision.subject_id].append(decision)
    standing = {}
    for cited in review.assessments:
        found = pick_decision(by_subject.get(cited.fact.id, []), sign_off)
        standing[cited.fact.subject.anchor.partition(":")[2]] = found
    answers = {
        q.id: pick_decision(by_subject.get(q.id, []), sign_off) for q in review.open_questions
    }
    return review, sign_off, standing, answers


def decision_table(request: Request, thread: str, review, standing, answers):
    """Build the table of the decisions a finished brief stands on."""
    rows = []
    for cited in review.assessments:
        tx_id = cited.fact.subject.anchor.partition(":")[2]
        decision = standing.get(tx_id)
        proposed = str(cited.fact.attributes["proposed_decision"]).capitalize()
        rows.append(
            {
                "transaction": Cell(tx_id),
                "proposed": Cell(proposed),
                "decision": Cell(final_word(decision) if decision else "No decision"),
                "by": Cell(
                    f"{decision.reviewer.name}, {decision.reviewer.role}" if decision else ""
                ),
                "date": Cell(
                    long_date(decision.date) if decision else "",
                    sort_value=decision.date if decision else "",
                ),
                "reason": Cell(decision.reason if decision else ""),
            }
        )
    for question in review.open_questions:
        decision = answers.get(question.id)
        rows.append(
            {
                "transaction": Cell(transaction_of_question(question)),
                "proposed": Cell("No usable assessment"),
                "decision": Cell(
                    decision.answer if decision and decision.answer else "Accepted as an assumption"
                ),
                "by": Cell(
                    f"{decision.reviewer.name}, {decision.reviewer.role}" if decision else ""
                ),
                "date": Cell(
                    long_date(decision.date) if decision else "",
                    sort_value=decision.date if decision else "",
                ),
                "reason": Cell(decision.reason if decision else ""),
            }
        )
    sort = request.query_params.get("sort")
    descending = request.query_params.get("dir") == "desc"

    def href_for(**changes: str) -> str:
        return (
            run_url(thread, "signed") + "?" + urlencode({**dict(request.query_params), **changes})
        )

    return build_table(
        DECISION_COLUMNS,
        rows,
        sort=sort,
        descending=descending,
        href_for=href_for,
        export_href=run_url(thread, "decisions.csv"),
        caption="Decisions made on the brief",
        empty="No decision was made on the brief.",
    )


def transaction_of_question(question: OpenQuestion) -> str:
    """Name the transaction an open question is about."""
    return question.about.anchor.partition(":")[2]


def routes(services: Services) -> list[Route]:
    """Return the signed page and the export of its decisions."""

    def load(request: Request):
        thread = request.path_params["thread"]
        info = read_run(services, thread)
        if info.status not in {"signed", "returned"}:
            return info, None
        return info, finished(info, services)

    def signed_page(request: Request) -> Response:
        info, found = load(request)
        if found is None:
            return RedirectResponse(run_url(info.thread_id), status_code=303)
        review, sign_off, standing, answers = found
        thread = info.thread_id
        statement_of = {
            c.fact.id: s for s in review.statements for c in s.facts if c.needs_decision
        }
        by_tx = {c.fact.subject.anchor.partition(":")[2]: c for c in review.assessments}
        selected = request.query_params.get("tx")
        cited = by_tx.get(selected or "") or next(iter(by_tx.values()), None)
        view = assessment_view(statement_of[cited.fact.id], cited) if cited else None
        scores = {tx: c.fact.attributes["risk_score"] for tx, c in by_tx.items()}
        asked = {
            transaction_of_question(q): answers.get(q.id) is not None or q.state != "open"
            for q in review.open_questions
        }
        rows = rows_of(info.state)
        pic = finished_picture(
            rows,
            scores,
            {tx: d for tx, d in standing.items() if d is not None},
            asked,
            (review.customer.user_id, review.customer.name),
            href_for=lambda tx: run_url(thread, "signed", tx=tx),
        )
        items = []
        for statement in review.statements:
            first = next(c for c in statement.facts if c.needs_decision)
            tx_id = first.fact.subject.anchor.partition(":")[2]
            items.append(
                {
                    "heading": statement.heading,
                    "text": statement.text,
                    "tx_id": tx_id,
                    "fact_id": first.fact.id,
                    "decision": standing.get(tx_id),
                }
            )
        decided = sum(1 for d in standing.values() if d is not None)
        word = "signed" if sign_off.outcome == "signed" else "returned"
        context = {
            "page_title": "Brief signed" if word == "signed" else "Brief returned",
            "answer": Answer(
                sentence=(
                    f"The brief for {review.customer.name} was {word} by {sign_off.reviewer.name}, "
                    f"{sign_off.reviewer.role}, on {long_date(sign_off.date)}."
                ),
                tiles=(
                    Tile("Transactions", str(len(by_tx))),
                    Tile("Decided", f"{decided} of {len(by_tx)}"),
                    Tile("Questions", str(len(review.open_questions))),
                ),
            ),
            "tabs_for": run_tabs(thread, info.status),
            "pic": pic,
            "statements": items,
            "view": view,
            "view_decision": standing.get(view.tx_id) if view else None,
            "current_tx": view.tx_id if view else None,
            "tx_href": lambda tx: run_url(thread, "signed", tx=tx),
            "sign_off": sign_off,
            "table": decision_table(request, thread, review, standing, answers),
            "carried_note": None,
        }
        return render(request, "transaction_monitoring/signed.html", context)

    def decisions_csv(request: Request) -> Response:
        info, found = load(request)
        if found is None:
            raise no_such_run(info.thread_id)
        review, _, standing, answers = found
        view = decision_table(request, info.thread_id, review, standing, answers)
        return PlainTextResponse(
            table_csv(view),
            media_type="text/csv",
            headers={"content-disposition": 'attachment; filename="decisions.csv"'},
        )

    return [
        Route("/runs/{thread}/signed", signed_page, methods=["GET"]),
        Route("/runs/{thread}/decisions.csv", decisions_csv, methods=["GET"]),
    ]


__all__ = ["routes", "transaction_of_question"]
