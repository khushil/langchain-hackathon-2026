"""Shared set-up of the policy pages' tests: the fake bundle on disk and a client over its pages."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from assessment.bundle import write_bundle
from assessment.fake import build_fake_bundle
from assessment.records import Bundle, NotIncluded
from assessment.texts import TextIndex, load_texts
from review_fakes import FakeRuns
from review_fixtures import DANA, TODAY
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app
from fsi_common.app.session import SessionCodec
from fsi_common.records import Brief, Person, Statement
from review_app import routes_policies
from review_app.context import Services
from review_app.drafts import DraftStore
from review_app.plugin import build_plugin
from review_app.policy_records import PolicyRecords

CORPUS = "harbour-mutual-bank"
BASE = f"/compliance-brief/policies/{CORPUS}"
SECRET = b"policy-test"


def _no_network(address: str, headers: object) -> bytes:
    raise OSError(f"the pages' tests make no network call ({address})")


def fake_texts() -> TextIndex:
    """Read the regulations and the Harbour Mutual Bank set, without a fetch."""
    return load_texts(CORPUS, opener=_no_network)


def write_fake(root: Path) -> tuple[Bundle, Path]:
    """Build the fake bundle and write it under a root, as the engine writes a run.

    Args:
        root: The folder that holds one folder for each corpus.

    Returns:
        The bundle and the root.
    """
    bundle = build_fake_bundle(fake_texts())
    write_bundle(bundle, root)
    return bundle, root


def make_app(root: Path, *, state_dir: Path | None = None, signed_in: Person | None = DANA):
    """Make the application with the topic's routes and the policy routes over a bundle root.

    Args:
        root: The folder that holds the bundles.
        state_dir: Where decisions are kept; memory when None.
        signed_in: The person signed in, or None for nobody.

    Returns:
        The client, and the record store the routes write to.
    """
    services = Services(runs=lambda: FakeRuns(), drafts=DraftStore(), today=lambda: TODAY)
    records = PolicyRecords(state_dir)
    plugin = build_plugin(services)
    # The plug-in lists the policy routes itself, bound to the services' own folder. Starlette
    # answers with the first route that matches, so the test's routes, bound to its root, go first.
    routes = [*routes_policies.routes(services, root=root, records=records), *plugin.routes]
    plugin = dataclasses.replace(plugin, routes=routes)
    app = create_app(AppConfig(secret=SECRET, topic_folders=()), topics=[plugin])
    cookies = {}
    if signed_in is not None:
        cookies[app.state.cookie_name] = SessionCodec(SECRET).encode(signed_in)
    return TestClient(app, cookies=cookies, follow_redirects=False), records


def text_of(html: str) -> str:
    """Return the words of a page: tags dropped, white space made single."""
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


LEFT_OUT_REASON = "its text is closed, so a clean clone does not hold it"
LEFT_OUT_COMMANDS = [
    "make regulations-check",
    "MODEL_BACKEND=record python -m assessment run harbour-mutual-bank --regulations SS1-23",
]


def left_out_bundle(bundle: Bundle, key: str = "SS1-23") -> Bundle:
    """Return a bundle as a run with one regulation left out writes it.

    Nothing of the regulation is in the register, the assessments, the facts, the seed matches or
    the gap report, and the index names it with a reason and the commands that bring it in.

    Args:
        bundle: A bundle that holds the regulation.
        key: The regulation to leave out.

    Returns:
        The bundle without it.
    """
    mine = f"{key} "
    register = bundle.obligation_register
    register = register.model_copy(
        update={
            "obligations": [o for o in register.obligations if o.regulation != key],
            "dispositions": [d for d in register.dispositions if d.regulation != key],
            "populations": [p for p in register.populations if p.regulation != key],
            "regulation_digests": {
                k: v for k, v in register.regulation_digests.items() if k != key
            },
        }
    )
    assessments = [a for a in bundle.assessments if not a.obligation_id.startswith(mine)]
    facts = [
        f for f in bundle.facts if not str(f.attributes.get("obligation_id", "")).startswith(mine)
    ]
    gone = {
        f.subject.source_id
        for f in bundle.facts
        if str(f.attributes.get("obligation_id", "")).startswith(mine)
    }
    statements = [
        Statement.build(heading=a.regulation, text=f"{a.obligation_id}: {a.gap}", cites=a.evidence)
        for a in assessments
        if a.state != "covered"
    ]
    report = Brief.build(
        request=bundle.gap_report.request,
        sources=[s for s in bundle.gap_report.sources if s not in gone],
        statements=statements,
        open_question_ids=[],
        model=bundle.gap_report.model,
        prompt_version=bundle.gap_report.prompt_version,
    )
    clause_map = [
        m.model_copy(update={"obligations": [o for o in m.obligations if not o.startswith(mine)]})
        for m in bundle.clause_map
    ]
    clause_map = [
        m
        if m.obligations or m.unmapped_reason
        else m.model_copy(update={"unmapped_reason": "outside the run's scope"})
        for m in clause_map
    ]
    index = bundle.index.model_copy(
        update={
            "scope": [o for o in bundle.index.scope if not o.startswith(mine)],
            "source_ids": [s for s in bundle.index.source_ids if s not in gone],
            "not_included": [
                NotIncluded(regulation=key, reason=LEFT_OUT_REASON, commands=LEFT_OUT_COMMANDS)
            ],
        }
    )
    return bundle.model_copy(
        update={
            "index": index,
            "obligation_register": register,
            "assessments": assessments,
            "judgements": [
                j for j in bundle.judgements if not j.request.obligation_id.startswith(mine)
            ],
            "candidates": [c for c in bundle.candidates if not c.obligation_id.startswith(mine)],
            "facts": facts,
            "clause_map": clause_map,
            "seed_matches": [m for m in bundle.seed_matches if m.regulation != key],
            "gap_report": report,
        }
    )


def write_left_out(root: Path, key: str = "SS1-23") -> tuple[Bundle, Path]:
    """Build the fake bundle with one regulation left out and write it under a root."""
    bundle = left_out_bundle(build_fake_bundle(fake_texts()), key)
    write_bundle(bundle, root)
    return bundle, root


def with_a_loose_statement(bundle: Bundle) -> Bundle:
    """Return a bundle whose gap report holds one more statement, citing no assessment's fact."""
    placed = {f for a in bundle.assessments for f in a.evidence}
    loose = next(f.id for f in bundle.facts if f.id not in placed)
    report = bundle.gap_report
    statements = [
        *report.statements,
        Statement.build(heading="DORA", text="A gap nobody assessed.", cites=[loose]),
    ]
    rebuilt = Brief.build(
        request=report.request,
        sources=report.sources,
        statements=statements,
        open_question_ids=[],
        model=report.model,
        prompt_version=report.prompt_version,
    )
    return bundle.model_copy(update={"gap_report": rebuilt})
