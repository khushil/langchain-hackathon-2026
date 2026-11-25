"""The reviewer's pages on the whole seeded document: what a person reads on each of them."""

from __future__ import annotations

import re

import pytest
from review_fakes import FakeRuns, examples_review
from review_fixtures import make_client
from review_seeded_support import Seeded, make_seeded, text_of

from fsi_common.records import Person
from review_app.context import PREFIX
from review_app.seed_fixture import DECISIONS, QUESTIONS

# Words that describe how the product works. No page but About may carry them.
METHOD_WORDS = (
    "plain-code",
    "plain code",
    "section reader",
    "reader's inference",
    "the reader",
    "second read",
    "inference",
    "replay",
    "mode 'record'",
    "recorded call",
    "prompt version",
)
PARAGRAPH_KIND = re.compile(r'class="map-cell map-(\w+)"[^>]*?data-para="([\d.]+)"')
HASH = re.compile(r"\b[0-9a-f]{32,}\b")


@pytest.fixture(scope="module")
def seeded() -> Seeded:
    """The seeded application: one brief waiting, one signed. Tests here only read it."""
    found = make_seeded()
    yield found
    found.stop()


@pytest.fixture()
def fresh() -> Seeded:
    """A seeded application a test may change."""
    found = make_seeded()
    yield found
    found.stop()


def kinds(html: str) -> dict[str, str]:
    """Return the kind of each box of the picture, by paragraph number."""
    return {number: kind for kind, number in PARAGRAPH_KIND.findall(html)}


def review(seeded: Seeded, thread: str | None = None, **query: str) -> str:
    """Read a run's review page, with a tab or a paragraph in the query."""
    suffix = "?" + "&".join(f"{k}={v}" for k, v in query.items()) if query else ""
    reply = seeded.client().get(f"{PREFIX}/runs/{thread or seeded.waiting}/review{suffix}")
    assert reply.status_code == 200, (query, reply.status_code)
    return reply.text


def post(seeded: Seeded, thread: str, action: str, **fields: str):
    """Post a form of the review page as the signed-in reviewer would."""
    digest = seeded.runs.review_request(thread).brief_digest
    return seeded.client().post(
        f"{PREFIX}/runs/{thread}/{action}", data={"brief_digest": digest, **fields}
    )


def answer_every_question(seeded: Seeded, thread: str) -> None:
    """Answer three questions and accept one as an assumption, as the reviewer's forms do."""
    request = seeded.runs.review_request(thread)
    ids = {q.about.anchor: q.id for q in request.open_questions}
    for question in QUESTIONS:
        fields = {"question_id": ids[question.paragraph]}
        if question.assumption:
            reply = post(seeded, thread, "assume", words=question.assumption, **fields)
        else:
            reply = post(
                seeded, thread, "answer", answer=question.answer, reason=question.reason, **fields
            )
        assert reply.status_code == 303


# --- Open questions and the paragraph notes say what is asked, never how the product works ------


def test_a_hash_appears_only_as_the_digest_a_person_signs_and_never_as_a_request_hash(seeded):
    """The document's digest and the brief's digest are part of the record and are shown short
    with the whole value on demand; a request hash is the engine's and is shown nowhere."""
    pages = [review(seeded, tab=tab) for tab in ("brief", "profile", "questions", "signoff")]
    client = seeded.client()
    for path in (f"{PREFIX}/", f"{PREFIX}/runs/{seeded.signed}/signed"):
        pages.append(client.get(path).text)
    for html in pages:
        text = text_of(html)
        for found in HASH.finditer(text):
            assert text[max(0, found.start() - 7) : found.start()] == "sha256:", found.group(0)


def test_no_page_but_about_describes_how_the_product_works(seeded):
    pages = [review(seeded, tab=tab) for tab in ("brief", "profile", "questions", "signoff")]
    pages += [review(seeded, para=n) for n in ("1.1", "6.6", "9.1", "2.4")]
    client = seeded.client()
    for path in (
        "/",
        f"{PREFIX}/",
        f"{PREFIX}/runs/{seeded.waiting}/facts",
        f"{PREFIX}/runs/{seeded.signed}/signed",
        f"{PREFIX}/runs/{seeded.signed}/facts",
        f"{PREFIX}/runs/{seeded.signed}/signed?para=1.1",
    ):
        reply = client.get(path)
        assert reply.status_code == 200, path
        pages.append(reply.text)
    for html in pages:
        text = text_of(html).lower()
        found = [w for w in METHOD_WORDS if w in text]
        assert found == [], found


def test_a_question_says_what_is_asked_why_it_is_not_known_and_what_changes(seeded):
    text = text_of(review(seeded, tab="questions"))
    for number in ("6.6", "7.4", "9.1", "9.4"):
        assert f"paragraph {number}" in text.lower()
    assert "Why it is not known" in text and "What changes with the answer" in text
    assert "Does paragraph 9.1 place an obligation on the firm?" in text
    assert "Paragraph 9.1, Paragraph 9.1" not in text  # the paragraph is named once in "Rests on"


# --- A stopped brief says why in words, with no hash and no internal name -------------------------


def test_a_stopped_brief_gives_a_sentence_without_a_hash_or_an_internal_mode_name():
    runs = FakeRuns()
    runs.add(
        "run-1",
        "failed",
        request={"document_id": "PS26-4", "firm_id": "FIRM-001", "request": "x", "sections": ["7"]},
        error=(
            "Replay has no recording for request "
            + "ab" * 32
            + ". Record it with a live call in mode 'record' first; replay never invents an answer."
        ),
    )
    page = make_client(runs).get(f"{PREFIX}/runs/run-1")
    text = text_of(page.text)
    assert "stopped before it was finished" in text
    assert not HASH.search(text)
    assert "mode" not in text and "replay" not in text.lower() and "record it" not in text.lower()
    assert 'data-hook="run-error"' in page.text


# --- Settled questions are not drawn as open ------------------------------------------------------


def test_the_picture_draws_the_four_questions_as_open_until_they_are_settled(seeded):
    found = kinds(review(seeded))
    assert [n for n, k in found.items() if k == "question"] == ["6.6", "7.4", "9.1", "9.4"]


def test_answering_every_question_takes_the_amber_off_the_picture_and_says_how_it_was_settled(
    fresh,
):
    thread = fresh.waiting
    answer_every_question(fresh, thread)
    html = review(fresh, thread)
    found = kinds(html)
    assert [n for n, k in found.items() if k == "question"] == []
    assert {found[n] for n in ("6.6", "7.4", "9.1", "9.4")} == {"settled"}
    assert "Answered by you" in html and "Accepted by you as an assumption" in html
    facts = fresh.client().get(f"{PREFIX}/runs/{thread}/facts").text
    assert [n for n, k in kinds(facts).items() if k == "question"] == []


def test_the_picture_of_a_signed_brief_has_no_open_question_either(seeded):
    html = seeded.client().get(f"{PREFIX}/runs/{seeded.signed}/facts").text
    found = kinds(html)
    assert len(found) == 48
    assert "question" not in set(found.values())
    assert {found[n] for n in ("6.6", "7.4", "9.1", "9.4")} == {"settled"}


# --- A carried question shows the answer, who gave it, when and why -------------------------------


def test_a_carried_question_shows_the_answer_who_gave_it_when_and_why():
    found = make_seeded()
    try:
        thread = found.start_another()
        text = text_of(review(found, thread, tab="questions"))
        carried = [q for q in QUESTIONS if q.answer]
        assert len(carried) == 3
        for question in carried:
            assert question.answer in text and question.reason in text
        assert text.count("Answered by you, on 24 November 2026") >= 3
        other = Person(name="Priya Shah", role="Compliance Analyst")
        page = found.client(other).get(f"{PREFIX}/runs/{thread}/review?tab=questions")
        said = text_of(page.text)
        assert (
            said.count("Answered by Dana Whitfield, Head of Compliance, on 24 November 2026") >= 3
        )
        assert "Settled earlier" not in text
        picture = kinds(review(found, thread))
        assert {picture[q.paragraph.removeprefix("para:")] for q in carried} == {"settled"}
        assert picture["7.4"] == "question"
    finally:
        found.stop()


# --- What the document requires leads the Brief tab -----------------------------------------------


def test_obligations_lead_the_brief_and_the_firm_statements_follow_with_one_badge_each(seeded):
    html = review(seeded)
    articles = re.findall(r'<article class="statement"[^>]*>(.*?)</article>', html, flags=re.S)
    assert len(articles) == 50
    firm = [a for a in articles if "profile-badge" in a]
    only_firm = [a for a in firm if "fact-link" not in a]
    first_only = articles.index(only_firm[0])
    assert first_only > 0 and articles[first_only:] == only_firm
    assert all("fact-link" in a for a in articles[:first_only])
    for statement in firm:
        assert statement.count('data-hook="profile-badge"') == 1
        badge = re.search(r'data-hook="profile-badge">(.*?)</li>', statement, flags=re.S).group(1)
        assert "tab=profile" in badge and "Needs a person" in badge
    assert len(only_firm) >= 4


def test_the_profile_badge_follows_the_profiles_state(fresh):
    thread = fresh.waiting
    reply = post(fresh, thread, "profile", outcome="accept", reason="The tables say this.")
    assert reply.status_code == 303
    html = review(fresh, thread)
    articles = re.findall(r'<article class="statement"[^>]*>(.*?)</article>', html, flags=re.S)
    badges = re.findall(r'data-hook="profile-badge">(.*?)</li>', html, flags=re.S)
    assert badges and all("Accepted by you" in b and "Needs a person" not in b for b in badges)
    assert len(articles) == 50


# --- Refusals keep what was typed, and say the reason once ---------------------------------------


def test_a_refused_answer_keeps_the_reason_that_was_typed(fresh):
    thread = fresh.waiting
    qid = fresh.runs.review_request(thread).open_questions[0].id
    reply = post(
        fresh, thread, "answer", question_id=qid, answer="   ", reason="Typed reason here."
    )
    assert reply.status_code == 422
    assert "Write the answer in your own words." in reply.text
    assert "Typed reason here." in reply.text
    other = post(fresh, thread, "answer", question_id=qid, answer="Typed answer here.", reason="  ")
    assert "Write what the answer rests on in your own words." in other.text
    assert "Typed answer here." in other.text


def test_a_refused_assumption_and_profile_keep_their_words(fresh):
    thread = fresh.waiting
    qid = fresh.runs.review_request(thread).open_questions[0].id
    reply = post(fresh, thread, "assume", question_id=qid, words="  ")
    assert reply.status_code == 422 and "Write the assumption in your own words." in reply.text
    reply = post(fresh, thread, "profile", outcome="amend", amendment="  ", reason="Kept reason.")
    assert reply.status_code == 422 and "Kept reason." in reply.text


def test_a_refused_return_says_its_reason_once(fresh):
    reply = post(fresh, fresh.waiting, "sign", outcome="returned", reason="  ")
    assert reply.status_code == 422
    words = "Write why you are returning the brief in your own words."
    assert text_of(reply.text).count(words) == 1


def test_a_sign_off_that_cannot_be_made_says_its_blocker_once(fresh):
    page = fresh.client().get(f"{PREFIX}/runs/{fresh.waiting}/review?tab=signoff")
    blocker = "The brief cannot be signed yet:"
    assert text_of(page.text).count(blocker) == 1


# --- A sign-off the engine refuses is shown ------------------------------------------------------


class RefusingRuns(FakeRuns):
    """A run service whose resume refuses the response and leaves the run at the review."""

    def submit(self, thread_id, response):
        """Validate as the service does, then leave the run waiting with the engine's reason."""
        run = self._run(thread_id)
        response.check_against(run.review.request)
        run.error = "The review step refused the response: it names a fact twice."
        return "awaiting_review"


def test_a_sign_off_the_engine_refuses_shows_its_sentence_and_does_not_open_the_signed_page():
    runs = RefusingRuns()
    review_ = examples_review()
    runs.add("run-1", "awaiting_review", review=review_)
    client = make_client(runs)
    from review_helpers import RUN, settle_everything

    review_ = settle_everything(client, runs)
    reply = client.post(
        f"{RUN}/sign", data={"brief_digest": review_.request.brief_digest, "outcome": "signed"}
    )
    assert reply.status_code != 303
    assert "The review step refused the response: it names a fact twice." in text_of(reply.text)
    assert "signed the brief" not in text_of(reply.text)


# --- The other pages ------------------------------------------------------------------------------


def test_the_facts_page_has_the_firm_profile_tab_when_the_brief_has_one(seeded):
    html = seeded.client().get(f"{PREFIX}/runs/{seeded.waiting}/facts").text
    tabs = re.search(r'<nav class="tabs".*?</nav>', html, flags=re.S).group(0)
    assert "Firm profile" in tabs and "tab=profile" in tabs


def test_a_signed_fact_with_wording_that_ends_in_a_full_stop_has_no_double_stop(seeded):
    amended = next(d for d in DECISIONS if d.outcome == "amend")
    reply = seeded.client().get(f"{PREFIX}/runs/{seeded.signed}/signed?fact={amended.fact_id}")
    text = text_of(reply.text)
    assert "Wording:" in text and ".." not in text


def test_the_list_tells_two_briefs_apart_by_who_reviewed_them_and_when(seeded):
    client = seeded.client()
    html = client.get(f"{PREFIX}/").text
    assert "Reviewed by" in html
    text = text_of(html)
    assert "Dana Whitfield, Head of Compliance, 24 November 2026" in text
    assert "Not yet" in text
    csv = client.get(f"{PREFIX}/runs.csv").text.splitlines()
    assert csv[0].split(",")[-1] == "Reviewed by"
    assert len(set(csv[1:])) == len(csv[1:])


def test_a_signed_out_start_panel_says_the_whole_sentence_in_view():
    page = make_client(FakeRuns(), signed_in=None).get(f"{PREFIX}/")
    assert "Sign in with your name and role to start a brief." in text_of(page.text)


def test_a_profile_source_names_its_fields_with_a_capital():
    found = make_seeded()
    try:
        html = review(found, tab="profile")
        labels = re.findall(r'<table class="data row-table".*?</table>', html, flags=re.S)
        heads = re.findall(r"<th scope=\"row\">([^<]*)</th>", labels[0])
        assert heads and all(h[0].isupper() for h in heads)
    finally:
        found.stop()


def test_the_picture_of_the_seeded_document_holds_all_48_paragraphs_in_ten_sections(seeded):
    html = review(seeded)
    assert len(kinds(html)) == 48
    assert len(re.findall(r'class="map-title"', html)) == 10
    assert "48 of 48 paragraphs of the document accounted for" in text_of(html)


def test_a_brief_returned_with_carried_decisions_says_so_in_words_and_lists_the_profile_once():
    found = make_seeded()
    try:
        thread = found.start_another()
        request = found.runs.review_request(thread)
        waiting = next(q for q in request.open_questions if q.state == "open")
        client = found.client()
        digest = request.brief_digest
        client.post(
            f"{PREFIX}/runs/{thread}/assume",
            data={
                "brief_digest": digest,
                "question_id": waiting.id,
                "words": "Treat it as a duty.",
            },
        )
        sent = client.post(
            f"{PREFIX}/runs/{thread}/sign",
            data={"brief_digest": digest, "outcome": "returned", "reason": "Read it again."},
        )
        assert sent.status_code == 303
        text = text_of(client.get(f"{PREFIX}/runs/{thread}/signed").text)
        assert "49 of 49 decisions were carried from an earlier review." in text
        assert text.count("Firm profile, 12 facts") == 1
        assert "Accepted, carried from an earlier review" in text
        earlier = text_of(client.get(f"{PREFIX}/runs/{found.signed}/signed").text)
        assert "carried from an earlier review" not in earlier
    finally:
        found.stop()


def test_a_carried_answer_is_the_one_the_brief_that_settled_it_holds_not_another_briefs():
    """Three finished or waiting briefs of one firm and document: the seeded one answers 9.1 one
    way, a second brief answers it another way, and a third carries the latest, which is the
    second's. Each page shows the answer its own brief stands on."""
    found = make_seeded()
    try:
        first_answer = next(q for q in QUESTIONS if q.paragraph == "para:9.1").answer
        seeded_signed = found.signed
        second = found.start_another()
        request = found.runs.review_request(second)
        ids = {q.about.anchor: q.id for q in request.open_questions}
        client = found.client()
        digest = request.brief_digest
        again = "No. Paragraph 9.1 lets small firms meet the requirements a year later."
        client.post(
            f"{PREFIX}/runs/{second}/answer",
            data={
                "brief_digest": digest,
                "question_id": ids["para:9.1"],
                "answer": again,
                "reason": "I read the paragraph again.",
            },
        )
        client.post(
            f"{PREFIX}/runs/{second}/assume",
            data={
                "brief_digest": digest,
                "question_id": ids["para:7.4"],
                "words": "Treat it as a duty.",
            },
        )
        done = client.post(
            f"{PREFIX}/runs/{second}/sign", data={"brief_digest": digest, "outcome": "signed"}
        )
        assert done.status_code == 303, done.text[:300]
        third = found.start_another()
        on_third = text_of(review(found, third, tab="questions"))
        assert again in on_third and first_answer not in on_third
        for thread, wanted, other in (
            (seeded_signed, first_answer, again),
            (second, again, first_answer),
        ):
            page = found.client().get(f"{PREFIX}/runs/{thread}/signed")
            on_page = text_of(page.text)
            assert wanted in on_page and other not in on_page
    finally:
        found.stop()
