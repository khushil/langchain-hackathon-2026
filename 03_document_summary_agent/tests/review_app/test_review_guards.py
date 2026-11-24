"""Guards on what the review route records: a moved brief, a script in words, the sign-off form."""

from __future__ import annotations

from html.parser import HTMLParser

from review_fakes import examples_review
from review_fixtures import make_client
from review_helpers import RUN, decide, move_the_brief, settle_everything, text_of

from fsi_common.examples.data import build_examples

STALE = "The brief changed after you opened it, so nothing was recorded."
SCRIPT = "<script>x</script>"
ESCAPED = "&lt;script&gt;x&lt;/script&gt;"


def test_a_sign_off_posted_against_an_older_digest_is_refused_in_words_and_submits_nothing(runs):
    c = make_client(runs)
    old = settle_everything(c, runs)
    move_the_brief(runs)
    page = c.post(
        f"{RUN}/sign", data={"brief_digest": old.request.brief_digest, "outcome": "signed"}
    )
    assert page.status_code == 409
    assert STALE in page.text
    assert runs.submitted == []
    assert c.get(f"{RUN}/signed").status_code == 303  # the run is still waiting for a reviewer


def test_a_return_posted_against_an_older_digest_is_refused_too(runs):
    c = make_client(runs)
    old = runs._runs["run-1"].review
    move_the_brief(runs)
    page = c.post(
        f"{RUN}/sign",
        data={
            "brief_digest": old.request.brief_digest,
            "outcome": "returned",
            "reason": "Needs another reading.",
        },
    )
    assert page.status_code == 409 and STALE in page.text
    assert runs.submitted == []


def _every_page_with_the_persons_words(runs):
    """Record words holding a script on every kind of record, sign, and read each page."""
    c = make_client(runs)
    review = runs._runs["run-1"].review
    ex = build_examples()
    decide(
        c,
        review,
        ex.fact_7_1,
        outcome="amend",
        amendment=f"Amended {SCRIPT}",
        reason=f"Reason {SCRIPT}",
    )
    decide(c, review, ex.fact_9_3, reason=f"Second reason {SCRIPT}")
    c.post(
        f"{RUN}/assume",
        data={
            "brief_digest": review.request.brief_digest,
            "question_id": review.question.id,
            "words": f"Assumed {SCRIPT}",
        },
    )
    pages = {
        "review, fact 7.1": c.get(f"{RUN}/review", params={"fact": ex.fact_7_1.id}),
        "review, fact 9.3": c.get(f"{RUN}/review", params={"fact": ex.fact_9_3.id}),
        "questions": c.get(f"{RUN}/review", params={"tab": "questions"}),
        "facts": c.get(f"{RUN}/facts"),
    }
    c.post(f"{RUN}/sign", data={"brief_digest": review.request.brief_digest, "outcome": "signed"})
    pages["signed"] = c.get(f"{RUN}/signed")
    pages["decisions csv"] = c.get(f"{RUN}/decisions.csv")
    return pages


def test_the_persons_own_words_are_escaped_on_the_review_facts_and_signed_pages(runs):
    pages = _every_page_with_the_persons_words(runs)
    for name in ("review, fact 7.1", "review, fact 9.3", "questions", "facts", "signed"):
        assert pages[name].status_code == 200, name
        assert "<script>x" not in pages[name].text, name
    assert pages["review, fact 7.1"].text.count(ESCAPED) >= 2  # the amendment and the reason
    assert ESCAPED in pages["review, fact 9.3"].text
    assert ESCAPED in pages["questions"].text
    assert pages["signed"].text.count(ESCAPED) >= 4  # three decisions' words and the assumption


def test_the_persons_own_words_are_kept_as_typed_in_the_export(runs):
    pages = _every_page_with_the_persons_words(runs)
    assert SCRIPT in pages["decisions csv"].text


def test_the_reason_a_return_gives_is_escaped_on_the_signed_page():
    from review_fakes import FakeRuns

    runs = FakeRuns()
    runs.add("run-1", "awaiting_review", review=examples_review())
    c = make_client(runs)
    review = runs._runs["run-1"].review
    c.post(
        f"{RUN}/sign",
        data={
            "brief_digest": review.request.brief_digest,
            "outcome": "returned",
            "reason": f"Return {SCRIPT}",
        },
    )
    page = c.get(f"{RUN}/signed")
    assert ESCAPED in page.text and "<script>x" not in page.text


class _SubmitControls(HTMLParser):
    """The controls of the sign-off form that submit it."""

    def __init__(self) -> None:
        super().__init__()
        self.in_form = False
        self.found: list[tuple[str, str | None, str | None]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.in_form = a.get("data-hook") == "signoff-form"
        elif self.in_form and tag == "button" and a.get("type", "submit") == "submit":
            self.found.append((tag, a.get("name"), a.get("value")))
        elif self.in_form and tag == "input" and a.get("type") in {"submit", "image"}:
            self.found.append((tag, a.get("name"), a.get("value")))

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_form = False


def submit_controls(html: str) -> list[tuple[str, str | None, str | None]]:
    parser = _SubmitControls()
    parser.feed(html)
    return parser.found


def test_the_sign_off_form_holds_two_submit_buttons_to_sign_or_to_return_and_nothing_else(client):
    html = client.get(f"{RUN}/review", params={"tab": "signoff"}).text
    assert submit_controls(html) == [
        ("button", "outcome", "signed"),
        ("button", "outcome", "returned"),
    ]
    assert "Sign the brief" in text_of(html) and "Return the brief" in text_of(html)


def test_the_scan_of_the_sign_off_form_sees_a_third_submit_control_in_planted_markup():
    planted = (
        '<form data-hook="signoff-form">'
        '<button type="submit" name="outcome" value="signed">Sign</button>'
        '<button name="outcome" value="returned">Return</button>'
        '<button type="submit" name="outcome" value="signed" title="Let the system sign">x</button>'
        "</form>"
    )
    assert len(submit_controls(planted)) == 3
