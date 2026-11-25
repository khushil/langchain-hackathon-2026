"""The policy pages: picture, register, one assessment, clauses, graph and gap report.

Every page reads a bundle the engine wrote. A decision on an assessment and the sign-off of the gap
report are recorded here only through ``review_route``, from a person who signed in.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from urllib.parse import urlencode

from assessment.bundle import BundleFileError, read_bundle
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from context.errors import ContextError
from fsi_common.app import current_person, render, sign_in_address
from fsi_common.app.pages import table_csv
from fsi_common.records import Decision, SignOff
from review_app import policy_view as view
from review_app import review_route
from review_app.context import Services, state_unavailable
from review_app.policy_records import PolicyRecords, PolicyRecordsError
from review_app.review_route import ReviewInputError

LOG = logging.getLogger("review_app.routes_policies")
ASSESSMENT = "compliance_brief/policy_assessment.html"
GAP_REPORT = "compliance_brief/policy_gap_report.html"
MEASURES = "compliance_brief/policy_measures.html"
BUNDLES_ENV = "POLICY_BUNDLES_DIR"
"""The folder that holds one folder per corpus, each a bundle the engine wrote."""
SIGN_IN_FIRST = "Sign in with your name and role before you decide on an assessment."
SIGN_IN_FIRST_REPORT = "Sign in with your name and role before you sign the gap report."
STALE = (
    "The assessment changed after you opened it, so nothing was recorded. Read it again and "
    "decide again."
)
STALE_REPORT = (
    "The gap report changed after you opened it, so nothing was recorded. Read it again and "
    "decide again."
)
SIGNED = "The gap report is signed, so no decision on it can be recorded now."
ALREADY_SIGNED = "The gap report is already signed, so it cannot be signed again."


def bundle_root(services: Services) -> Path | None:
    """Return the folder that holds the bundles, or None when none is set.

    Args:
        services: The services; their state folder holds ``assessments`` when the application
            is durable.

    Returns:
        The folder ``POLICY_BUNDLES_DIR`` names, else ``<state folder>/assessments``, else None.
    """
    named = os.environ.get(BUNDLES_ENV)
    if named:
        return Path(named)
    return None if services.state_dir is None else Path(services.state_dir) / "assessments"


def pages_link(services: Services, root: Path | None = None) -> Callable[[], str | None]:
    """Make the function that gives the address of the first corpus's policy pages, or None.

    Args:
        services: The services.
        root: The folder of bundles; ``bundle_root(services)`` when absent.

    Returns:
        A function that returns the picture's address when a bundle is held, else None, so a page
        links to the policy pages only when they have something to show.
    """

    def link() -> str | None:
        folder = root or bundle_root(services)
        if folder is None or not folder.is_dir():
            return None
        held = sorted(p.name for p in folder.iterdir() if (p / "bundle.json").is_file())
        return f"{view.PREFIX}/{held[0]}" if held else None

    return link


PRIVATE_RECORDING = "SS1/23's assessment is read from a private recording."


def about_lines(services: Services, root: Path | None = None) -> tuple[str, ...]:
    """Give the sentence About says once when a bundle's SS1/23 assessment is a private recording.

    The text of SS1/23 is closed, so an assessment that includes it was recorded in a private
    folder and is only replayed here. A fake run, and a bundle that left SS1/23 out, give nothing.

    Args:
        services: The services.
        root: The folder of bundles; ``bundle_root(services)`` when absent.

    Returns:
        The sentence, once, when any bundle is a recorded or replayed run that holds SS1/23; else
        an empty tuple.
    """
    folder = root or bundle_root(services)
    if folder is None or not folder.is_dir():
        return ()
    for index in sorted(folder.glob("*/bundle.json")):
        try:
            run = json.loads(index.read_text("utf-8")).get("run")
            held = json.loads((index.parent / "register.json").read_text("utf-8"))
        except (OSError, ValueError) as exc:
            LOG.warning("The bundle in %s could not be read for About: %s", index.parent, exc)
            continue
        if run in {"record", "replay"} and "SS1-23" in held.get("regulation_digests", {}):
            return (PRIVATE_RECORDING,)
    return ()


class _Bundles:
    """Reads each corpus's bundle once, and again when its index file changes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: dict[tuple[Path, str], tuple[int, view.PolicyData]] = {}
        self._documents: dict[str, tuple[view.PolicyDocument, ...]] = {}

    def get(self, root: Path | None, corpus: str) -> view.PolicyData:
        if PurePosixPath(corpus).name != corpus or corpus in {"", ".", ".."} or root is None:
            raise HTTPException(404, f"There is no assessment of {corpus}.")
        folder = root / corpus
        index = folder / "bundle.json"
        try:
            stamp = index.stat().st_mtime_ns
        except OSError as exc:
            raise HTTPException(404, f"There is no assessment of {corpus}.") from exc
        with self._lock:
            held = self._held.get((root, corpus))
            if held is not None and held[0] == stamp:
                return held[1]
            try:
                bundle = read_bundle(folder)
                documents = self._documents.get(corpus) or view.read_documents(corpus)
            except (BundleFileError, ContextError) as exc:
                LOG.error("The assessment of %s could not be read: %s", corpus, exc, exc_info=exc)
                raise HTTPException(
                    503,
                    f"The assessment of {corpus} could not be read. Tell the person who runs "
                    "this server.",
                ) from exc
            self._documents[corpus] = documents
            data = view.PolicyData(bundle, documents)
            self._held[(root, corpus)] = (stamp, data)
            return data


def routes(
    services: Services, *, root: Path | None = None, records: PolicyRecords | None = None
) -> list[Route]:
    """Return the policy pages' routes, bound to the services.

    Args:
        services: The services; the bundles are read from ``bundle_root(services)`` by default.
        root: The folder of bundles, for a test or a build that holds them elsewhere.
        records: Where decisions are kept; files in the services' state folder by default.

    Returns:
        The routes, to be listed in the topic's plug-in.
    """
    bundles = _Bundles()
    held: list[PolicyRecords] = []

    def store() -> PolicyRecords:
        if records is not None:
            return records
        if not held:
            held.append(PolicyRecords(services.state_dir))
        return held[0]

    def data_of(request: Request) -> view.PolicyData:
        return bundles.get(root or bundle_root(services), request.path_params["corpus"])

    def tabs(data: view.PolicyData) -> list[tuple[str, str, str]]:
        return [
            ("picture", "Picture", view.href_page(data)),
            ("register", "Register", view.href_page(data, "register")),
            ("clauses", "Clauses", view.href_page(data, "clauses")),
            ("graph", "Graph", view.href_page(data, "graph")),
            ("gap-report", "Gap report", view.href_page(data, "gap-report")),
            ("measures", "Measures", view.href_page(data, "measures")),
        ]

    def common(request: Request, data: view.PolicyData) -> dict:
        return {
            "tabs_for": tabs(data),
            "name": data.name,
            "sign_in": sign_in_address(request),
            "found_kind": lambda state: view.STATE_KIND[state],
            "found_word": lambda state: view.STATE_WORDS[state],
        }

    def decisions_of(data: view.PolicyData) -> dict[str, Decision]:
        try:
            return store().decisions(data.corpus)
        except PolicyRecordsError as exc:
            raise state_unavailable(exc, "The decisions could not be read") from exc

    def signed_off(data: view.PolicyData) -> SignOff | None:
        try:
            return store().sign_off(data.corpus, data.bundle.gap_report.id)
        except PolicyRecordsError as exc:
            raise state_unavailable(exc, "The sign-off could not be read") from exc

    def is_signed(data: view.PolicyData) -> bool:
        held_sign_off = signed_off(data)
        return held_sign_off is not None and held_sign_off.outcome == "signed"

    def open_gap(
        request: Request,
        data: view.PolicyData,
        decisions: dict[str, Decision],
        *,
        after: str | None = None,
    ) -> str | None:
        """Give the next gap without the signed-in person's decision, while decisions are open."""
        person = current_person(request)
        if person is None or is_signed(data):
            return None
        return view.next_open_gap(data, decisions, person=person, after=after)

    def table_args(request: Request, page: str) -> dict:
        sort = request.query_params.get("sort")
        descending = request.query_params.get("dir") == "desc"
        base = request.url.path

        def href_for(**changes: str) -> str:
            return base + "?" + urlencode({**dict(request.query_params), **changes})

        export = (
            base
            + ".csv"
            + (
                "?" + urlencode({"sort": sort, "dir": "desc" if descending else "asc"})
                if sort
                else ""
            )
        )
        return {
            "sort": sort,
            "descending": descending,
            "href_for": href_for,
            "export_href": export,
        }

    def picture_page(request: Request) -> Response:
        data = data_of(request)
        decisions = decisions_of(data)
        context = {
            **common(request, data),
            "page_title": f"{data.name} against the regulations",
            "answer": view.picture_answer(data, decisions),
            "picture": view.picture_view(data),
            "left_out": view.not_included_lines(data),
            "first_open_gap": open_gap(request, data, decisions),
        }
        return render(request, "compliance_brief/policy_picture.html", context)

    def measures_page(request: Request) -> Response:
        data = data_of(request)
        figures = view.measure_figures(data)
        context = {
            **common(request, data),
            "page_title": "How the findings compare with the seeded cases",
            "answer": view.measures_answer(figures, data),
            "figures": figures,
            "proposal": view.proposal_sentence(data),
        }
        return render(request, MEASURES, context)

    def register_page(request: Request) -> Response:
        data = data_of(request)
        context = {
            **common(request, data),
            "page_title": "Register of obligations",
            "answer": view.register_answer(data),
            "table": view.register_table(data, **table_args(request, "register")),
            "questions": view.open_questions(data),
        }
        return render(request, "compliance_brief/policy_register.html", context)

    def register_csv(request: Request) -> Response:
        data = data_of(request)
        table = view.register_table(data, **table_args(request, "register"))
        return PlainTextResponse(
            table_csv(table),
            media_type="text/csv",
            headers={"content-disposition": 'attachment; filename="register.csv"'},
        )

    def clauses_page(request: Request) -> Response:
        data = data_of(request)
        context = {
            **common(request, data),
            "page_title": "Clauses in force",
            "answer": view.clauses_answer(data),
            "table": view.clauses_table(data, **table_args(request, "clauses")),
        }
        return render(request, "compliance_brief/policy_clauses.html", context)

    def clauses_csv(request: Request) -> Response:
        data = data_of(request)
        table = view.clauses_table(data, **table_args(request, "clauses"))
        return PlainTextResponse(
            table_csv(table),
            media_type="text/csv",
            headers={"content-disposition": 'attachment; filename="clauses.csv"'},
        )

    def graph_page(request: Request) -> Response:
        data = data_of(request)
        edges = view.graph_edges(data)
        context = {
            **common(request, data),
            "page_title": "Document graph",
            "answer": view.graph_answer(edges, data),
            "edges": edges,
        }
        return render(request, "compliance_brief/policy_graph.html", context)

    def obligation_id_of(request: Request) -> str:
        return f"{request.path_params['key']} {request.path_params['anchor']}"

    def assessment_context(
        request: Request,
        data: view.PolicyData,
        page: view.AssessmentPage,
        *,
        form_error: str | None = None,
        form_values: dict | None = None,
    ) -> dict:
        decisions = decisions_of(data)
        decision = decisions.get(page.assessment.id) if page.assessment else None
        return {
            **common(request, data),
            "page_title": f"{page.obligation.label} against the documents in force",
            "answer": view.assessment_answer(page, decision),
            "page": page,
            "decision": decision,
            "regulation_name": view.REGULATION_NAMES[page.obligation.regulation],
            "decide_action": f"{view.href_obligation(data, page.obligation.obligation_id)}/decide",
            "signed": is_signed(data),
            "next_open_gap": open_gap(
                request, data, decisions, after=page.obligation.obligation_id
            ),
            "form_error": form_error,
            "form_values": form_values or {},
        }

    def assessment_page(request: Request) -> Response:
        data = data_of(request)
        page = view.assessment_page(data, obligation_id_of(request))
        if page is None:
            raise HTTPException(404, "There is no such obligation that applies to this firm.")
        return render(request, ASSESSMENT, assessment_context(request, data, page))

    def decide_action(request: Request, form) -> Response:
        data = data_of(request)
        obligation_id = obligation_id_of(request)
        page = view.assessment_page(data, obligation_id)
        if page is None or page.assessment is None:
            raise HTTPException(404, "There is no such obligation that applies to this firm.")
        address = view.href_obligation(data, obligation_id)

        def refuse(status: int, words: str) -> Response:
            values = {k: str(v) for k, v in form.items()}
            context = assessment_context(request, data, page, form_error=words, form_values=values)
            return render(request, ASSESSMENT, context, status=status)

        person = current_person(request)
        if person is None:
            return refuse(403, SIGN_IN_FIRST)
        if str(form.get("assessment_id", "")) != page.assessment.id:
            return refuse(409, STALE)
        if is_signed(data):
            return refuse(409, SIGNED)
        try:
            decision = review_route.decide_assessment(
                page.assessment,
                outcome=str(form.get("outcome", "")),
                reason=str(form.get("reason", "")),
                amendment=str(form.get("amendment", "")) or None,
                person=person,
                on=services.today(),
            )
        except ReviewInputError as exc:
            return refuse(422, str(exc))
        except ValidationError as exc:
            return refuse(422, f"That cannot be recorded: {exc.errors()[0]['msg']}.")
        try:
            store().put_decision(data.corpus, decision)
        except PolicyRecordsError as exc:
            raise state_unavailable(exc, "Nothing was recorded") from exc
        return RedirectResponse(address, status_code=303)

    def gap_context(
        request: Request,
        data: view.PolicyData,
        *,
        form_error: str | None = None,
        form_values: dict | None = None,
    ) -> dict:
        decisions = decisions_of(data)
        blocker = view.cannot_sign_because(data, decisions, person=current_person(request))
        return {
            **common(request, data),
            "page_title": "Gap report",
            "answer": view.gap_report_answer(data, decisions, blocker),
            "statements": view.gap_statements(data, decisions),
            "unplaced": view.unplaced_statements(data),
            "report": data.bundle.gap_report,
            "sign_off": signed_off(data),
            "blocker": blocker,
            "sign_action": f"{view.href_page(data, 'gap-report')}/sign",
            "form_error": form_error,
            "form_values": form_values or {},
        }

    def gap_report_page(request: Request) -> Response:
        data = data_of(request)
        return render(request, GAP_REPORT, gap_context(request, data))

    def sign_action(request: Request, form) -> Response:
        data = data_of(request)

        def refuse(status: int, words: str) -> Response:
            values = {k: str(v) for k, v in form.items()}
            context = gap_context(request, data, form_error=words, form_values=values)
            return render(request, GAP_REPORT, context, status=status)

        person = current_person(request)
        if person is None:
            return refuse(403, SIGN_IN_FIRST_REPORT)
        report = data.bundle.gap_report
        if str(form.get("brief_digest", "")) != report.content_digest:
            return refuse(409, STALE_REPORT)
        if is_signed(data):
            return refuse(409, ALREADY_SIGNED)
        outcome = str(form.get("outcome", ""))
        if outcome == "signed":
            problem = view.cannot_sign_because(data, decisions_of(data), person=person)
            if problem:
                return refuse(422, problem)
        try:
            sign_off = review_route.sign_gap_report(
                report,
                outcome=outcome,
                reason=str(form.get("reason", "")) or None,
                person=person,
                on=services.today(),
            )
        except ReviewInputError as exc:
            return refuse(422, str(exc))
        except ValidationError as exc:
            return refuse(422, f"That cannot be recorded: {exc.errors()[0]['msg']}.")
        try:
            store().put_sign_off(data.corpus, sign_off)
        except PolicyRecordsError as exc:
            raise state_unavailable(exc, "Nothing was recorded") from exc
        return RedirectResponse(view.href_page(data, "gap-report"), status_code=303)

    def recording(action: Callable[[Request, object], Response]):
        async def endpoint(request: Request) -> Response:
            form = await request.form()
            return await run_in_threadpool(action, request, form)

        return endpoint

    prefix = "/policies/{corpus}"
    return [
        Route(f"{prefix}", picture_page, methods=["GET"]),
        Route(f"{prefix}/register", register_page, methods=["GET"]),
        Route(f"{prefix}/register.csv", register_csv, methods=["GET"]),
        Route(f"{prefix}/clauses", clauses_page, methods=["GET"]),
        Route(f"{prefix}/clauses.csv", clauses_csv, methods=["GET"]),
        Route(f"{prefix}/graph", graph_page, methods=["GET"]),
        Route(f"{prefix}/gap-report", gap_report_page, methods=["GET"]),
        Route(f"{prefix}/measures", measures_page, methods=["GET"]),
        Route(f"{prefix}/gap-report/sign", recording(sign_action), methods=["POST"]),
        Route(
            f"{prefix}/obligations/{{key}}/{{anchor:path}}/decide",
            recording(decide_action),
            methods=["POST"],
        ),
        Route(f"{prefix}/obligations/{{key}}/{{anchor:path}}", assessment_page, methods=["GET"]),
    ]
