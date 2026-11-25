"""What the review pages share: reading a run for review, and saying where each proposal stands."""

from __future__ import annotations

from collections.abc import Mapping

from starlette.exceptions import HTTPException
from starlette.responses import RedirectResponse, Response

from fsi_common.app import Cell, Column
from fsi_common.records import Decision, Fact, Person, SignOff
from review_app.context import RunInfo, Services, earlier_decisions, read_run, run_url, runs_of
from review_app.picture import Picture, build_picture
from review_app.review_model import ReviewModel
from review_app.service import NotAwaitingReviewError, RunNotFoundError
from review_app.wording import decision_line, pick_decision, proposal_words
from utils.kyc_state import ReviewRequest
from utils.records import customer_of_anchor

APPLICATION_COLUMNS = (
    Column("application", "Application"),
    Column("applicant", "Applicant"),
    Column("proposal", "Proposal"),
    Column("checks", "Checks"),
    Column("questions", "Open questions"),
    Column("decision", "Decision"),
)
CARRIED_WORDS = "carried from an earlier review"


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
        raise HTTPException(404, f"There is no run {thread}.") from exc
    carried = [q.decision_id for q in request.open_questions if q.decision_id]
    model = ReviewModel(
        request,
        services.drafts.get(thread, person),
        viewer=person,
        earlier=earlier_decisions(services, thread, carried),
    )
    return info, request, model


def signed_decisions(info: RunInfo) -> dict[str, Decision]:
    """Return the decision a finished batch stands on for each subject, by subject id."""
    sign_off = (
        SignOff.model_validate(info.state["sign_off"]) if info.state.get("sign_off") else None
    )
    held: dict[str, list[Decision]] = {}
    for data in (info.state.get("decisions") or {}).values():
        decision = Decision.model_validate(data)
        held.setdefault(decision.subject_id, []).append(decision)
    return {s: pick_decision(c, sign_off) for s, c in held.items()}


def decision_cell(
    fact: Fact, model: ReviewModel | None, decided: Mapping[str, Decision], viewer: Person | None
) -> Cell:
    """Say where one proposal stands, for a table cell."""
    if model is not None:
        state = model.fact_states[fact.id]
        if not state.settled:
            return Cell("Needs a person", status="needs_person")
        words = decision_line(state.decision, viewer)
        return Cell(words + (f", {CARRIED_WORDS}" if state.kind == "carried" else ""))
    decision = decided.get(fact.id)
    return Cell(decision_line(decision, viewer) if decision else "No decision")


def application_rows(
    info: RunInfo,
    proposals: Mapping[str, Fact],
    questions: Mapping[str, int],
    model: ReviewModel | None,
    viewer: Person | None,
) -> list[dict[str, Cell]]:
    """Return one table row for each application of the batch, in application order."""
    decided = {} if model is not None else signed_decisions(info)
    names = {c: a.get("name") for c, a in info.state.get("applicants", {}).items()}
    rows = []
    for fact in sorted(proposals.values(), key=lambda f: f.subject.anchor):
        customer = customer_of_anchor(fact.subject.anchor)
        settled = fact.attributes["settled"]
        waiting = questions.get(customer, 0)
        rows.append(
            {
                "application": Cell(
                    customer,
                    href=run_url(info.thread_id, "applications", customer),
                    title=f"Open the application {customer}",
                ),
                "applicant": Cell(names.get(customer) or "Name not established"),
                "proposal": Cell(proposal_words(fact)),
                "checks": Cell("Settled by the checks")
                if settled
                else Cell("Needs a person", status="needs_person"),
                "questions": Cell(str(waiting), sort_value=f"{waiting:04d}"),
                "decision": decision_cell(fact, model, decided, viewer),
            }
        )
    return rows


def picture_of(info: RunInfo, settled: Mapping[str, str]) -> Picture:
    """Draw the batch with each address leading to the application's page."""
    return build_picture(
        info.state,
        settled=settled,
        href_for=lambda customer: run_url(info.thread_id, "applications", customer),
    )
