"""The user guide's transaction monitoring steps, followed on the seeded application and the saved
calls: each quoted phrase is on the page and in the guide, and the walk ends in a signed brief."""

from __future__ import annotations

import re
import time

import pytest
from review_support import DANA, run_path, text
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app
from fsi_common.app.session import SessionCodec
from review_app.context import Services
from review_app.drafts import DraftStore
from review_app.plugin import build_plugin
from review_app.seed import SEED_DATE, seed_transaction_monitoring
from utils import PROJECT_ROOT
from workflow.runs import MonitorRuns

GUIDE = (PROJECT_ROOT.parent / "docs" / "user-guide.md").read_text(encoding="utf-8")
SECRET = b"guide"
BASE = "/transaction-monitoring"


def steps() -> str:
    return GUIDE[GUIDE.index("## Transaction monitoring") :]


class Walk:
    """The seeded application on the saved calls, and the person walking through it."""

    def __init__(self) -> None:
        self.runs = MonitorRuns(models=None)
        self.services = Services(
            runs=lambda: self.runs, drafts=DraftStore(), today=lambda: SEED_DATE
        )
        app = create_app(
            AppConfig(secret=SECRET, topic_folders=()), topics=[build_plugin(self.services)]
        )
        seed_transaction_monitoring(self.services, build_plugin)
        cookie = {app.state.cookie_name: SessionCodec(SECRET).encode(DANA)}
        self.client = TestClient(app, cookies=cookie, follow_redirects=True)
        self.waiting = next(t for t in self.runs.list_runs() if self.runs.status(t) != "signed")
        self.signed = next(t for t in self.runs.list_runs() if self.runs.status(t) == "signed")

    def request(self):
        return self.runs.review_request(self.waiting)

    def fact_id(self, tx: str) -> str:
        found = {
            c.fact.subject.anchor.partition(":")[2]: c.fact.id for c in self.request().assessments
        }
        return found[tx]

    def post(self, path: str, **data):
        body = {"brief_digest": self.request().brief_digest, **data}
        return self.client.post(f"{run_path(self.waiting, path)}", data=body)

    def get(self, url: str):
        return self.client.get(url)

    def close(self) -> None:
        self.runs.close()
        self.services.drafts.close()


@pytest.fixture()
def walk():
    walking = Walk()
    yield walking
    walking.close()


def assert_on(page, *phrases: str) -> None:
    shown = " ".join(text(page).split()) if not isinstance(page, str) else page
    for phrase in phrases:
        assert phrase in shown, phrase
        assert phrase in steps(), f"the guide does not quote: {phrase}"


def test_the_pages_say_what_the_guide_says_they_say(walk):
    assert_on(
        walk.get("/"), "1 customer review is waiting for a reviewer.", "Transaction monitoring"
    )
    assert_on(
        walk.get(f"{BASE}/"),
        "2 runs so far: 1 waiting for a reviewer, 1 signed.",
        "Runs, newest first",
        "Priya Shah, whole stream",
        "Waiting for a reviewer",
        "Priya Shah, before 19 October 2026",
        "Dana Whitfield, Head of Compliance, 25 November 2026",
        "Needs a decision",
        "Decided earlier, nothing changed",
        "Not assessed yet",
        "Assess a customer's transactions",
        "Assess the transactions",
    )
    review = walk.get(run_path(walk.waiting, "review"))
    assert_on(
        review,
        "The brief for Priya Shah has 10 transactions to decide. 4 still need your decision "
        "before it can be signed.",
        "6 of 10",
        "0 of 0",
        "Questions settled",
        "Open questions",
        "Earlier decisions",
        "Sign-off",
        "TX-1009 at LuxWatch Online, 1250.0 GBP in GB (online): proposed block at a risk score "
        "of 75 and a confidence of 0.65.",
        "Carried: agreed 25 November 2026",
    )
    assert_on(
        walk.get(run_path(walk.waiting, "review") + "?tab=history"),
        "What reviewers decided about Priya Shah before",
        "Export CSV",
    )
    assert_on(
        walk.get(run_path(walk.waiting, "review") + "?tab=questions"),
        "The brief carries no open questions.",
    )
    assert_on(
        walk.get(run_path(walk.waiting, "review") + "?tx=TX-1007"),
        "Proposed decision",
        "Approve",
        "8 of 100",
        "0.92",
        "Checks",
        "Passed",
        "Agree with the proposal",
        "Give my own decision",
        "Disagree",
        "My words for it",
        "Your reason",
        "Record my decision",
        "Next transaction to decide",
    )
    assert_on(
        walk.get(run_path(walk.waiting, "review") + "?tab=signoff"),
        "The brief cannot be signed yet: 4 transactions without a decision.",
        "Why you are returning the brief, if you return it",
        "Sign the brief",
        "Return the brief",
    )


def test_the_refusals_the_guide_names_are_the_pages_words(walk):
    empty = walk.post("decide", fact_id=walk.fact_id("TX-1007"), outcome="accept", reason="")
    assert empty.status_code == 422
    assert_on(empty, "Write your reason in your own words.")
    unchosen = walk.post(
        "decide", fact_id=walk.fact_id("TX-1009"), outcome="amend", reason="x", wording="y"
    )
    assert unchosen.status_code == 422
    assert_on(unchosen, "Choose approve or block for your own decision.")
    disagree = walk.post(
        "decide", fact_id=walk.fact_id("TX-1009"), outcome="reject", reason="Not convinced."
    )
    assert disagree.status_code == 200
    for tx in ("TX-1007", "TX-1008", "TX-1010"):
        walk.post("decide", fact_id=walk.fact_id(tx), outcome="accept", reason="Usual for her.")
    assert_on(
        walk.get(run_path(walk.waiting, "review") + "?tab=signoff"),
        "You disagreed with 1 transaction. Return the brief so that it can be assessed again.",
    )


def test_the_walk_the_guide_describes_ends_in_a_signed_brief(walk):
    accepted = walk.post(
        "decide", fact_id=walk.fact_id("TX-1007"), outcome="accept", reason="Her usual weekly shop."
    )
    assert_on(accepted, "7 of 10")
    own = walk.post(
        "decide",
        fact_id=walk.fact_id("TX-1009"),
        outcome="amend",
        final="approve",
        wording="Her own card, at home, a large purchase for her.",
        reason="The card was used in the UK, as it is every week.",
    )
    assert own.status_code == 200
    for tx in ("TX-1008", "TX-1010"):
        walk.post("decide", fact_id=walk.fact_id(tx), outcome="accept", reason="Usual for her.")
    assert_on(
        walk.get(run_path(walk.waiting, "review") + "?tab=signoff"),
        "Every transaction and question is settled, so it is ready for you to sign.",
    )
    done = walk.post("sign", outcome="signed")
    assert done.status_code == 200
    assert_on(
        done,
        "The brief for Priya Shah was signed by Dana Whitfield, Head of Compliance, on "
        "25 November 2026.",
        "Digest signed",
        "Decisions made on the brief",
        "Export CSV",
    )
    assert "Reviewer" in text(done) and "Outcome" in text(done)
    csv = walk.get(run_path(walk.waiting, "decisions.csv"))
    assert csv.headers["content-disposition"] == 'attachment; filename="decisions.csv"'
    assert csv.text.count("\n") == 11
    older = walk.get(run_path(walk.signed, "signed"))
    assert "Decisions made on the brief" in text(older)


def test_a_later_run_carries_what_a_signed_run_decided(walk):
    for tx in ("TX-1007", "TX-1008", "TX-1009", "TX-1010"):
        walk.post("decide", fact_id=walk.fact_id(tx), outcome="accept", reason="Usual for her.")
    assert walk.post("sign", outcome="signed").status_code == 200
    started = walk.client.post(f"{BASE}/runs", data={"user_id": "USR-001"})
    assert started.status_code == 200
    deadline = time.monotonic() + 60
    newest = walk.runs.list_runs()[0]
    while walk.runs.status(newest) == "running" and time.monotonic() < deadline:
        time.sleep(0.1)
    page = walk.get(run_path(newest, "review"))
    assert "Carried: agreed" in text(page)
    assert_on(
        page,
        "Every transaction and question is settled, so it is ready for you to sign.",
    )
    assert "On the saved calls every proposal is unchanged, so all ten transactions" in steps()
    assert "Carried: agreed" in steps()
    assert re.search(r"Assess the transactions", steps())
