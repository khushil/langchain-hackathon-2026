"""What the pages draw and list: the marks of the stream and the statements with their states."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fsi_common.records import Decision
from review_app.review_model import AssessmentState, QuestionState, ReviewModel
from review_app.stream_picture import MarkInput, StreamPicture, build_picture
from utils.records import TRANSACTION_SCHEME
from utils.review import ReviewRequest

AMOUNT = "{amount} {currency}"


def rows_of(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the transaction rows a run read, in time order.

    Args:
        state: The run's state, which holds each unit and its line of the data file.

    Returns:
        The rows as the data file gives them.
    """
    prefix = f"{TRANSACTION_SCHEME}:"
    rows = [
        json.loads(state["unit_text"][unit["id"]])
        for unit in state.get("units", {}).values()
        if unit["anchor"].startswith(prefix)
    ]
    return sorted(rows, key=lambda row: (row["timestamp"], row["transaction_id"]))


def _mark(row: Mapping[str, Any], state: str, score: Any, href: str | None) -> MarkInput:
    return MarkInput(
        tx_id=row["transaction_id"],
        user_id=row["user_id"],
        timestamp=row["timestamp"],
        merchant=row["merchant"],
        amount=AMOUNT.format(**row),
        state=state,
        score=score,
        href=href,
    )


def idle_marks(rows: Sequence[Mapping[str, Any]]) -> list[MarkInput]:
    """Mark every transaction as not assessed yet, with no address to open.

    Args:
        rows: The transaction rows.

    Returns:
        One mark for each row.
    """
    return [_mark(row, "idle", None, None) for row in rows]


def _state_of_assessment(state: AssessmentState) -> str:
    if state.rejected:
        return "rejected"
    return {"yours": "decided", "carried": "carried", "needs": "needs"}[state.kind]


def _state_of_question(state: QuestionState) -> str:
    return "answered" if state.settled else "question"


def review_picture(
    rows: Sequence[Mapping[str, Any]],
    request: ReviewRequest,
    model: ReviewModel,
    *,
    href_for: Callable[[str], str],
) -> StreamPicture:
    """Draw a brief that waits for a reviewer: each transaction marked by where it stands.

    Args:
        rows: The run's transaction rows.
        request: The request the reviewer was shown.
        model: The review, which says where each assessment and question stands.
        href_for: Gives the address that opens a transaction, from its id.

    Returns:
        The picture, with one lane for the brief's customer.
    """
    assessed = {c.fact.subject.anchor: c for c in request.assessments}
    questions = {s.question.about.anchor: s for s in model.question_states}
    marks = []
    for row in rows:
        anchor = f"{TRANSACTION_SCHEME}:{row['transaction_id']}"
        if anchor in assessed:
            cited = assessed[anchor]
            state = _state_of_assessment(model.fact_states[cited.fact.id])
            marks.append(
                _mark(
                    row, state, cited.fact.attributes["risk_score"], href_for(row["transaction_id"])
                )
            )
        elif anchor in questions:
            marks.append(
                _mark(
                    row,
                    _state_of_question(questions[anchor]),
                    None,
                    href_for(row["transaction_id"]),
                )
            )
        else:
            marks.append(_mark(row, "idle", None, None))
    customer = request.customer
    return build_picture(marks, lanes=[(customer.user_id, customer.name)])


def finished_picture(
    rows: Sequence[Mapping[str, Any]],
    scores: Mapping[str, Any],
    decisions: Mapping[str, Decision],
    question_tx: Mapping[str, bool],
    customer: tuple[str, str],
    *,
    href_for: Callable[[str], str],
) -> StreamPicture:
    """Draw a finished brief: each transaction marked by what the reviewer decided.

    Args:
        rows: The run's transaction rows.
        scores: The risk score of each assessed transaction, by transaction id.
        decisions: The decision standing on each assessed transaction, by transaction id.
        question_tx: For each transaction asked about, whether it was answered.
        customer: The customer as (user id, name).
        href_for: Gives the address that opens a transaction, from its id.

    Returns:
        The picture.
    """
    marks = []
    for row in rows:
        tx_id = row["transaction_id"]
        decision = decisions.get(tx_id)
        if tx_id in question_tx:
            state = "answered" if question_tx[tx_id] else "question"
        elif decision is None:
            state = "idle"
        else:
            state = "rejected" if decision.outcome == "reject" else "decided"
        href = href_for(tx_id) if tx_id in scores else None
        marks.append(_mark(row, state, scores.get(tx_id), href))
    return build_picture(marks, lanes=[customer])


def overview_picture(
    rows: Sequence[Mapping[str, Any]],
    covering: Mapping[str, tuple[str, str]],
    lanes: Sequence[tuple[str, str]],
    *,
    href_for: Callable[[str, str], str],
) -> StreamPicture:
    """Draw every customer's transactions, each marked by the newest run that covers it.

    Args:
        rows: Every transaction row.
        covering: For each transaction a run covers, the run's id and the state its mark shows.
        lanes: The customers as (user id, name).
        href_for: Gives the address that opens a transaction of a run.

    Returns:
        The picture; a transaction no run covers is marked as not assessed yet and does not link.
    """
    marks = []
    for row in rows:
        tx_id = row["transaction_id"]
        run = covering.get(tx_id)
        if run is None or run[1] == "idle":
            marks.append(_mark(row, "idle", None, None))
            continue
        thread, state = run
        marks.append(_mark(row, state, None, href_for(thread, tx_id)))
    return build_picture(marks, lanes=lanes)


@dataclass(frozen=True)
class StatementItem:
    """One statement of the brief as the page lists it, with where its assessment stands."""

    heading: str | None
    text: str
    tx_id: str
    fact_id: str
    state: AssessmentState


def statement_items(request: ReviewRequest, model: ReviewModel) -> list[StatementItem]:
    """List the statements of a brief with the state of the assessment each rests on.

    Args:
        request: The request the reviewer was shown.
        model: The review.

    Returns:
        One item for each statement, in the brief's order.
    """
    items = []
    for statement in request.statements:
        cited = next(c for c in statement.facts if c.needs_decision)
        items.append(
            StatementItem(
                heading=statement.heading,
                text=statement.text,
                tx_id=cited.fact.subject.anchor.partition(":")[2],
                fact_id=cited.fact.id,
                state=model.fact_states[cited.fact.id],
            )
        )
    return items


@dataclass(frozen=True)
class Unassessed:
    """A transaction with no assessment on the brief, listed beside the statements."""

    tx_id: str
    words: str
    href: str
    status: str
    badge: str


def unassessed_items(
    request: ReviewRequest, model: ReviewModel, rows: Sequence[Mapping[str, Any]], *, href: str
) -> list[Unassessed]:
    """List the transactions that have a question and no assessment on the brief.

    Args:
        request: The request the reviewer was shown.
        model: The review.
        rows: The run's transaction rows.
        href: The address of the open questions.

    Returns:
        One item for each such transaction, in time order.
    """
    on_brief = {c.fact.subject.anchor for c in request.assessments}
    by_anchor = {s.question.about.anchor: s for s in model.question_states}
    found = []
    for row in rows:
        anchor = f"{TRANSACTION_SCHEME}:{row['transaction_id']}"
        if anchor in on_brief or anchor not in by_anchor:
            continue
        settled = by_anchor[anchor].settled
        found.append(
            Unassessed(
                tx_id=row["transaction_id"],
                words=(
                    f"{row['transaction_id']} at {row['merchant']}, "
                    f"{AMOUNT.format(**row)} in {row['country']}: no usable assessment, so a "
                    "person decides it through a question."
                ),
                href=href,
                status="normal" if settled else "failed",
                badge="Question answered" if settled else "Needs a person",
            )
        )
    return found
