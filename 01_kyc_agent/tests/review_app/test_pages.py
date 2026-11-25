"""The pages as a signed-in reviewer reads them, over the real engine on the scripted reader."""

import re

import pytest
from support import BASE, DANA, SAM, SMALL, make_client, new_runs, start_run, switch_to, text_of


@pytest.fixture(scope="module")
def waiting():
    runs = new_runs()
    thread = start_run(runs, SMALL)
    return runs, thread


@pytest.fixture()
def client(waiting):
    return make_client(waiting[0])


def run_path(waiting, *parts):
    return "/".join([BASE, "runs", waiting[1], *parts])


def hooks(html: str, name: str) -> list[str]:
    return re.findall(rf'data-hook="{name}"', html)


def test_the_start_page_opens_on_its_answer_with_the_batches_and_the_form(client):
    page = client.get(f"{BASE}/")
    assert page.status_code == 200
    assert "1 batch so far: 1 waiting for a reviewer." in text_of(page.text)
    assert len(hooks(page.text, "tile")) == 3 and len(hooks(page.text, "exhibit")) == 1
    assert 'action="/kyc/runs"' in page.text
    assert page.text.count('name="customers"') == 25
    assert "Start the batch" in page.text


def test_an_empty_start_page_says_so():
    page = make_client(new_runs()).get(f"{BASE}/")
    assert "No batch has been started" in text_of(page.text)


def test_the_start_form_is_a_link_to_sign_in_when_nobody_is(waiting):
    page = make_client(waiting[0], signed_in=None).get(f"{BASE}/")
    assert 'action="/kyc/runs"' not in page.text
    assert "/signin?next=" in page.text


def test_starting_a_batch_needs_a_person_and_a_choice():
    runs = new_runs()
    nobody = make_client(runs, signed_in=None)
    refused = nobody.post(f"{BASE}/runs", data={"customers": ["CUST-001"]})
    assert refused.status_code == 403 and "Sign in" in refused.text
    me = make_client(runs)
    none = me.post(f"{BASE}/runs", data={})
    assert none.status_code == 422 and "Choose at least one application." in none.text
    odd = me.post(f"{BASE}/runs", data={"customers": ["CUST-999"]})
    assert odd.status_code == 422 and "CUST-999" in odd.text
    assert runs.list_runs() == []


def test_starting_a_batch_leads_to_it_and_a_second_is_refused_while_one_runs():
    runs = new_runs()
    me = make_client(runs)
    started = me.post(f"{BASE}/runs", data={"customers": ["CUST-001", "CUST-004"]})
    assert started.status_code == 303 and started.headers["location"].startswith("/kyc/runs/")
    again = me.post(f"{BASE}/runs", data={"customers": ["CUST-001"]})
    assert again.status_code in {303, 409}
    thread = started.headers["location"].rsplit("/", 1)[1]
    from support import wait_for

    wait_for(runs, thread)
    assert me.get(started.headers["location"]).headers["location"].endswith("/review")


def test_a_batch_waiting_leads_to_its_review_and_an_unknown_one_is_a_404(waiting, client):
    assert client.get(run_path(waiting)).headers["location"] == run_path(waiting, "review")
    missing = client.get(f"{BASE}/runs/none/review")
    assert missing.status_code == 404 and "There is no run none." in text_of(missing.text)


def test_the_batch_page_leads_with_the_picture_then_the_table(client, waiting):
    page = client.get(run_path(waiting, "review"))
    html = page.text
    assert page.status_code == 200
    sentence = text_of(re.search(r'data-hook="sentence">(.*?)</h1>', html, re.S).group(1))
    assert sentence.startswith("4 applications were screened against 14 list entries: 2 settled")
    assert html.index('data-hook="picture"') < html.index('data-hook="table"')
    assert len(hooks(html, "picture-row")) == 4
    assert html.count('data-hook="picture-cell"') == 4 * 14
    assert "56 of 56 screenings accounted for" in text_of(html)
    assert len(hooks(html, "tile")) == 3
    for customer in SMALL:
        assert f"/kyc/runs/{waiting[1]}/applications/{customer}" in html


def test_a_picture_cell_says_its_state_in_words_and_never_by_colour_alone(client, waiting):
    html = client.get(run_path(waiting, "review")).text
    cell = re.search(r'<a [^>]*data-hook="picture-cell"[^>]*data-state="needs"[^>]*>', html).group(
        0
    )
    assert 'title="' in cell and 'aria-label="' in cell
    assert "Needs a person" in cell
    assert re.search(r'data-state="settled"', html) and re.search(r'data-state="none"', html)


def test_the_key_names_every_entry_by_number_beside_the_picture(client, waiting):
    text = text_of(client.get(run_path(waiting, "review")).text)
    assert "1 Dmitry Volkonskiy" in text and "14 Nadia Karimova" in text
    assert "Sanctions list" in text and "PEP list" in text


def test_the_application_page_shows_the_words_the_facts_quote_and_the_proposal(client, waiting):
    html = client.get(run_path(waiting, "applications", "CUST-016")).text
    text = text_of(html)
    assert "<mark>Rurik Zelenko</mark>" in html
    assert "Rurik Zelenko (CUST-016): proposed high risk, reject" in text
    assert "Settled by the checks" in text
    assert "Exact name and date of birth match with Rurik Zelenko" in text
    assert hooks(html, "decision-form")
    assert "Passed" in text


def test_an_unsettled_application_puts_both_readings_side_by_side(client, waiting):
    html = client.get(run_path(waiting, "applications", "CUST-018")).text
    same = re.search(r'data-hook="reading-same"[^>]*>(.*?)</section>', html, re.S).group(1)
    different = re.search(r'data-hook="reading-different"[^>]*>(.*?)</section>', html, re.S).group(
        1
    )
    assert "The same person" in text_of(same) and "The names are identical" in text_of(same)
    assert "A different person" in text_of(different)
    assert "The dates of birth differ" in text_of(different)
    assert html.index('data-hook="reading-same"') < html.index('data-hook="reading-different"')
    assert "The checks did not settle" in text_of(html)
    assert hooks(html, "answer-form") and hooks(html, "assume-form")


def test_an_application_with_no_question_has_no_answer_form(client, waiting):
    html = client.get(run_path(waiting, "applications", "CUST-001")).text
    assert not hooks(html, "answer-form") and not hooks(html, "reading-same")
    assert "No likeness to any of the 14 list entries" in text_of(html)


def test_a_failed_check_is_shown_with_its_words(waiting):
    from kyc_fakes import ScriptedReader, reading_of

    from workflow.runs import KycRuns

    runs = KycRuns(
        models=ScriptedReader(
            readings={"CUST-001": reading_of("CUST-001", name="Sarah Mitchell-Jones")}
        )
    )
    thread = start_run(runs, ["CUST-001"])
    html = make_client(runs).get(f"{BASE}/runs/{thread}/applications/CUST-001").text
    text = text_of(html)
    assert "is not written in the application" in text.lower()
    assert "Not screened" in text
    assert "name could not be checked" in text


def test_an_application_that_is_not_in_the_batch_is_a_404_in_words(client, waiting):
    page = client.get(run_path(waiting, "applications", "CUST-002"))
    assert page.status_code == 404 and "CUST-002" in text_of(page.text)


def test_nobody_signed_in_sees_no_form_and_a_link_to_sign_in(waiting):
    html = (
        make_client(waiting[0], signed_in=None)
        .get(run_path(waiting, "applications", "CUST-018"))
        .text
    )
    assert not hooks(html, "decision-form") and not hooks(html, "answer-form")
    assert "Sign in" in html


def test_the_screenings_tab_lists_every_screening_and_exports_the_same_rows(client, waiting):
    page = client.get(run_path(waiting, "screenings"))
    assert page.status_code == 200 and "56 screenings" in text_of(page.text)
    csv_text = client.get(run_path(waiting, "screenings.csv")).text
    lines = csv_text.strip().splitlines()
    assert len(lines) == 57 and lines[0].startswith("Application,Entry")


def test_the_applications_csv_holds_a_row_for_each_application(client, waiting):
    lines = client.get(run_path(waiting, "applications.csv")).text.strip().splitlines()
    assert len(lines) == 5 and lines[0].startswith("Application,Applicant,Proposal")


def test_the_sign_off_page_says_what_blocks_it_and_offers_no_approval_by_a_machine(client, waiting):
    html = client.get(run_path(waiting, "signoff")).text
    text = text_of(html)
    assert "The batch cannot be signed yet: 4 proposals without a decision" in text
    assert "You are acting as Dana Whitfield, Head of Compliance" in text
    assert "disabled" in re.search(r'<button[^>]*value="signed"[^>]*>', html).group(0)
    assert not re.search(r"auto[- ]?approve|approve all", text, re.I)


def test_every_page_is_free_of_method_notes_hashes_and_internal_names(client, waiting):
    pages = [
        f"{BASE}/",
        run_path(waiting, "review"),
        run_path(waiting, "screenings"),
        run_path(waiting, "signoff"),
        *[run_path(waiting, "applications", c) for c in SMALL],
    ]
    banned = re.compile(
        r"sha256|[0-9a-f]{32}|fact:[0-9a-f]{16}|question:[0-9a-f]{16}|\.v1\b|replay|MODEL_BACKEND"
        r"|recording|claude|plain[- ]code|not legal, compliance or regulatory advice",
        re.I,
    )
    for path in pages:
        found = banned.findall(text_of(client.get(path).text))
        assert found == [], f"{path}: {found}"
        html = client.get(path).text
        assert "\u2014" not in html and "\u2013" not in html


def test_another_person_sees_none_of_the_first_persons_pending_work(waiting):
    runs = waiting[0]
    client = make_client(runs)
    request = runs.review_request(waiting[1])
    proposal = next(
        c.fact for s in request.statements for c in s.facts if c.fact.kind == "proposal"
    )
    done = client.post(
        run_path(waiting, "decide"),
        data={
            "brief_digest": request.brief_digest,
            "fact_id": proposal.id,
            "outcome": "accept",
            "reason": "Matches.",
        },
    )
    assert done.status_code == 303
    mine = text_of(client.get(run_path(waiting, "review")).text)
    assert "1 of 4" in mine
    switch_to(client, SAM)
    theirs = text_of(client.get(run_path(waiting, "review")).text)
    assert "0 of 4" in theirs and "Dana Whitfield" not in theirs.split("Proposals decided")[0]
    assert DANA.name  # the first person is still Dana


def test_the_list_sentence_says_batches_for_more_than_one():
    runs = new_runs()
    start_run(runs, ["CUST-001"])
    start_run(runs, ["CUST-004"])
    page = make_client(runs).get(f"{BASE}/")
    assert "2 batches so far: 2 waiting for a reviewer." in text_of(page.text)
    assert "batchs" not in text_of(page.text)
