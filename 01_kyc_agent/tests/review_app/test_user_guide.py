"""The user guide's KYC steps, followed on the seeded application: each quoted phrase is there."""

import re

import pytest
from kyc_fakes import ScriptedReader
from starlette.testclient import TestClient
from support import text_of

from fsi_common.app import AppConfig, create_app
from fsi_common.app.session import SessionCodec
from review_app import seed, service
from review_app.context import Services
from review_app.plugin import NAME, build_plugin
from utils import PROJECT_ROOT

GUIDE = (PROJECT_ROOT.parent / "docs" / "user-guide.md").read_text(encoding="utf-8")


def steps() -> str:
    return GUIDE[GUIDE.index("## KYC onboarding") :]


@pytest.fixture(params=["scripted", "recorded"])
def app(tmp_path, request):
    service.use_models(ScriptedReader() if request.param == "scripted" else None)
    services = Services()
    config = AppConfig(secret=b"s", topic_folders=(), state_dir=tmp_path, seed=NAME)
    application = create_app(config, topics=[build_plugin(services)])
    client = TestClient(application, follow_redirects=True)
    client.cookies.set(application.state.cookie_name, SessionCodec(b"s").encode(seed.REVIEWER))
    runs = services.runs()
    waiting = next(t for t in runs.list_runs() if runs.status(t) == "awaiting_review")
    signed = next(t for t in runs.list_runs() if runs.status(t) == "signed")
    client.services = services
    yield client, waiting, signed
    service.use_models(None)
    runs.close()
    services.drafts.close()


def assert_on(page: str, *phrases: str) -> None:
    text = " ".join(text_of(page).replace("&#39;", "'").replace("&#34;", '"').split())
    for phrase in phrases:
        assert phrase in text, phrase
        assert phrase in steps(), f"the guide does not quote: {phrase}"


def test_the_pages_say_what_the_guide_says_they_say(app):
    client, waiting, signed = app
    assert_on(client.get("/").text, "1 batch is waiting for a reviewer.")
    assert_on(
        client.get("/kyc/").text,
        "2 batches so far: 1 waiting for a reviewer, 1 signed.",
        "All 25 applications",
        "Start a batch",
        "Start the batch",
    )
    review = client.get(f"/kyc/runs/{waiting}/review").text
    assert_on(
        review,
        "25 applications were screened against 14 list entries: 13 settled by the checks and "
        "12 for a person to settle. 25 proposals and 14 questions still need your decision "
        "before it is signed.",
        "350 of 350 screenings accounted for: 18 kept as facts and 332 with no likeness",
        "0 of 25",
        "0 of 14",
    )
    assert_on(
        client.get(f"/kyc/runs/{waiting}/screenings").text,
        "No likeness: the names score 0.26 against Dmitry Volkonskiy on the sanctions list, "
        "below the floor of 0.60.",
        "Export CSV",
    )
    assert_on(
        client.get(f"/kyc/runs/{waiting}/applications/CUST-001").text,
        "Details read from the application",
        "Low risk, approve",
        "Settled by the checks",
        "Passed",
        "Your risk level and decision, if you amend",
        "Record my decision",
    )
    assert_on(
        client.get(f"/kyc/runs/{waiting}/applications/CUST-018").text,
        "High risk, reject",
        "Is Ivana Strahov (CUST-018) the same person as Ivana Strahov on the sanctions list "
        "(Ostmark asset freeze), or a different person?",
        "The same person",
        "A different person",
        "The dates of birth differ: 1996-03-14 on the application, 1985-08-07 on the list.",
        "Your answer",
        "What your answer rests on",
        "Record my answer",
    )
    assert_on(
        client.get(f"/kyc/runs/{waiting}/applications/CUST-015").text,
        "senior government official in Valdoria",
        "Or accept it as an assumption, in your words",
        "Accept as an assumption",
    )
    assert_on(
        client.get(f"/kyc/runs/{waiting}/signoff").text,
        "The batch cannot be signed yet: 25 proposals without a decision and 14 questions not "
        "answered or accepted.",
        "Why you are returning the batch, if you return it",
        "Sign the batch",
        "Return the batch",
    )
    assert_on(
        client.get(f"/kyc/runs/{signed}/signed").text,
        "Digest signed",
        "Decisions made on the batch",
    )


def test_the_walk_the_guide_describes_ends_in_a_signed_batch(app):
    client, waiting, _ = app
    base = f"/kyc/runs/{waiting}"

    def digest() -> str:
        return client.services.runs().review_request(waiting).brief_digest

    request = client.services.runs().review_request(waiting)
    proposals = {
        c.fact.subject.anchor.partition(":")[2]: c.fact.id
        for s in request.statements
        for c in s.facts
        if c.fact.kind == "proposal"
    }
    for customer, fact_id in proposals.items():
        body = {"brief_digest": digest(), "fact_id": fact_id, "outcome": "accept", "reason": "ok"}
        if customer == "CUST-018":
            body |= {"outcome": "amend", "amendment": "Low risk, approve.", "reason": "Another"}
        assert client.post(f"{base}/decide", data=body).status_code == 200
    for question in request.open_questions:
        route, field = ("answer", {"answer": "A different person.", "reason": "Dates differ."})
        assert (
            client.post(
                f"{base}/{route}",
                data={"brief_digest": digest(), "question_id": question.id, **field},
            ).status_code
            == 200
        )
    page = client.get(f"{base}/signoff").text
    assert_on(page, "Sign the batch")
    done = client.post(f"{base}/sign", data={"brief_digest": digest(), "outcome": "signed"})
    assert done.status_code == 200
    assert_on(done.text, "signed the batch of 25 applications.")


def test_the_signed_batch_and_a_later_batch_read_as_the_guide_says(app):
    import time

    client, waiting, signed = app
    runs = client.services.runs()
    state = runs.result(signed)
    answers = [d for d in state["decisions"].values() if d["outcome"] == "answer"]
    proposals = [d for d in state["decisions"].values() if d["subject_id"].startswith("fact:")]
    assert (len(proposals), len(answers), len(state["sign_off"]["assumptions"])) == (25, 12, 2)
    started = client.post("/kyc/runs", data={"customers": ["CUST-001", "CUST-018"]})
    assert started.status_code == 200
    thread = next(t for t in runs.list_runs() if t not in (waiting, signed))
    for _ in range(600):
        if runs.status(thread) != "running":
            break
        time.sleep(0.05)
    assert_on(
        client.get(f"/kyc/runs/{thread}/review").text,
        "Accepted by you, on 24 November 2026, carried from an earlier review",
    )
    assert_on(
        client.get(f"/kyc/runs/{thread}/applications/CUST-018").text,
        "Answered by you",
    )
    assert "Since then these changed:" in steps()


def step_14_counts(text: str = "") -> tuple[int, int, int]:
    """Read the counts step 14 of the guide gives for the signed batch."""
    found = re.search(
        r"shows the (\d+) proposals decided one by one, (\d+) answers and (\d+) assumptions?",
        text or steps(),
    )
    assert found, "step 14 of the guide gives no such sentence"
    return tuple(int(n) for n in found.groups())


def signed_counts(client, signed) -> tuple[int, int, int]:
    state = client.services.runs().result(signed)
    decisions = list(state["decisions"].values())
    return (
        sum(d["subject_id"].startswith("fact:") for d in decisions),
        sum(d["outcome"] == "answer" for d in decisions),
        len(state["sign_off"]["assumptions"]),
    )


def test_step_14_gives_the_counts_of_the_signed_batch(app):
    client, _, signed = app
    assert step_14_counts() == signed_counts(client, signed)


def test_a_wrong_count_in_step_14_is_found(app):
    client, _, signed = app
    planted = steps().replace("12 answers and 2 assumptions", "13 answers and 1 assumption")
    assert planted != steps()
    assert step_14_counts(planted) != signed_counts(client, signed)
