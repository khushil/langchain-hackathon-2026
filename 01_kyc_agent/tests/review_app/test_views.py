"""The small views: marked quotes, the words for decisions and changes, and the run pages."""

from kyc_fakes import ScriptedReader
from support import BASE, DANA, SAM, make_client, new_runs, start_run, text_of

from fsi_common.records import Decision
from review_app.application_view import build_application, mark_quotes
from review_app.run_data import read_run_data
from review_app.wording import (
    attribute_label,
    attribute_value,
    difference_label,
    pick_decision,
    sentence_end,
)
from workflow.runs import KycRuns


def marked(segments):
    return [s.text for s in segments if s.marked]


def test_a_quote_is_marked_where_it_occurs_word_for_word_and_white_space_may_differ():
    text = "Name: Viktor  Harlan. Born 2 July 1968."
    assert marked(mark_quotes(text, ["Viktor Harlan", "2 July 1968"])) == [
        "Viktor  Harlan",
        "2 July 1968",
    ]
    assert "".join(s.text for s in mark_quotes(text, ["Viktor Harlan"])) == text


def test_a_quote_that_is_not_there_or_lies_inside_another_marks_nothing_more():
    text = "Name: Viktor Harlan."
    assert (
        mark_quotes(text, ["Somebody Else"]) == (mark_quotes(text, []))
        or marked(mark_quotes(text, ["Somebody Else"])) == []
    )
    assert marked(mark_quotes(text, ["Viktor Harlan", "Harlan"])) == ["Viktor Harlan"]
    assert marked(mark_quotes(text, [""])) == []


def test_an_application_the_batch_does_not_hold_has_no_view():
    runs = new_runs()
    state = runs.result(start_run(runs, ["CUST-001"]))
    assert build_application(read_run_data(state), {}, "CUST-009") is None
    view = build_application(read_run_data(state), state["readings"], "CUST-001")
    assert view.heading == "Sarah Mitchell (CUST-001)"
    assert view.sentence == (
        "Sarah Mitchell (CUST-001): proposed low risk, approve. Settled by the checks."
    )
    assert (view.no_likeness, view.not_screened, view.screenings) == (14, 0, ())


def test_the_sentence_of_an_unsettled_application_counts_its_questions():
    runs = new_runs()
    state = runs.result(start_run(runs, ["CUST-015"]))
    view = build_application(read_run_data(state), state["readings"], "CUST-015")
    assert view.sentence.endswith("The checks did not settle it: 2 questions for a person.")
    assert {q.question.reason for q in view.questions} == {"ambiguous_meaning", "missing_data"}
    assert all(q.readings is not None for q in view.questions)


def test_words_for_labels_values_and_endings():
    assert attribute_label("name_score") == "Name score"
    assert attribute_label("something_new") == "Something new"
    assert attribute_value(None) == "None" and attribute_value(True) == "Yes"
    assert attribute_value(["a", "b"]) == "a; b" and attribute_value([]) == "None"
    assert sentence_end(" Low risk ") == "Low risk." and sentence_end("Why?") == "Why?"
    assert difference_label("attributes.basis") == "Basis"
    assert difference_label("quote") == "The quoted words"
    assert (
        difference_label("checks.name-score.v1")
        == "The score is the measure of the two names (result)"
    )


def test_the_decision_a_finished_batch_stands_on_is_the_signers_then_the_latest():
    runs = new_runs()
    request = runs.review_request(start_run(runs, ["CUST-001"]))
    fact = next(c.fact for s in request.statements for c in s.facts if c.fact.kind == "proposal")

    def made(who, on):
        return Decision.on(fact, outcome="accept", reason="r", reviewer=who, date=on)

    early, late, sam = made(DANA, "2026-11-20"), made(DANA, "2026-11-24"), made(SAM, "2026-11-25")
    assert pick_decision([], None) is None
    assert pick_decision([early, late, sam], None) == sam
    from fsi_common.records import SignOff

    sign_off = SignOff.build(
        brief_id=request.brief_id,
        brief_digest=request.brief_digest,
        reviewer=DANA,
        date="2026-11-24",
        outcome="signed",
        assumptions=[],
    )
    assert pick_decision([early, late, sam], sign_off) == late


def test_a_stopped_batch_says_so_in_words_and_a_running_one_how_far_it_has_come():
    reader = ScriptedReader(fail_for=("CUST-004",))
    runs = KycRuns(models=reader)
    thread = runs.start({"request": "r", "customer_ids": ["CUST-004"]})
    from support import wait_for

    wait_for(runs, thread, "failed")
    page = make_client(runs).get(f"{BASE}/runs/{thread}")
    text = text_of(page.text)
    assert page.status_code == 200
    assert "The batch stopped before it was finished." in text
    assert "The model call for CUST-004 failed" in text
    assert 'http-equiv="refresh"' not in page.text
    assert make_client(runs).get(f"{BASE}/runs/{thread}/applications/CUST-004").status_code == 404
    assert make_client(runs).get(f"{BASE}/runs/{thread}/screenings").status_code == 404


def test_an_application_page_counts_its_screenings_from_the_run_and_types_none():
    from utils import PROJECT_ROOT

    runs = new_runs()
    state = runs.result(start_run(runs, ["CUST-015"]))
    view = build_application(read_run_data(state), state["readings"], "CUST-015")
    assert view.screenings_total == len(view.screenings) + view.no_likeness + view.not_screened
    assert view.screenings_total == 14
    template = (PROJECT_ROOT / "review_app" / "templates" / "kyc" / "application.html").read_text()
    assert "of the 14" not in template and "view.screenings_total" in template
