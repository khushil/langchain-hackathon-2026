"""What the page does with an empty answer, in a browser at 1366 by 768, and what the guide says."""

import re
from pathlib import Path

from review_browser_support import SIZES, Served  # noqa: F401

GUIDE = Path(__file__).resolve().parents[3] / "docs" / "user-guide.md"
QUESTIONS = "/compliance-brief/runs/run-1/review?tab=questions"
SENTENCE = "Write the answer in your own words."
PROMPT = "Please fill out this field."
BASIS = "The paragraph says may and gives a later date."


def answer_form(page):
    form = page.locator('[data-hook="answer-form"]').first
    return form, form.locator("textarea[name=answer]"), form.locator("textarea[name=reason]")


def record(page, requests, answer: str):
    form, box, basis = answer_form(page)
    box.fill(answer)
    basis.fill(BASIS)
    form.get_by_role("button", name="Record my answer").click()
    page.wait_for_timeout(600)
    return form, box, basis


def test_an_empty_answer_is_stopped_by_the_browser_before_anything_is_sent(browser, served):
    context, page = served.open(browser, SIZES[0])
    sent: list[str] = []
    page.on("request", lambda r: sent.append(r.url) if r.method == "POST" else None)
    page.goto(served.base_url + QUESTIONS)
    before = page.url
    _, box, _ = record(page, sent, "")
    assert sent == [] and page.url == before
    assert box.evaluate("e => e.validity.valueMissing") is True
    assert box.evaluate("e => e.validationMessage") == PROMPT
    assert SENTENCE not in page.content()
    context.close()


def test_an_answer_of_only_spaces_is_sent_and_the_page_refuses_it_in_words(browser, served):
    context, page = served.open(browser, SIZES[0])
    sent: list[str] = []
    page.on("request", lambda r: sent.append(r.url) if r.method == "POST" else None)
    page.goto(served.base_url + QUESTIONS)
    record(page, sent, "   ")
    assert len(sent) == 1 and sent[0].endswith("/answer")
    assert SENTENCE in page.inner_text("body")
    _, box, basis = answer_form(page)
    assert basis.input_value() == BASIS
    context.close()


def guide_problems(text: str) -> list[str]:
    """Name what step 22 and the failure table say about an empty answer that the page does not."""
    found = []
    step = re.search(r"^22\. .*$", text, re.M)
    if step is None:
        return ["the guide has no step 22"]
    words = step.group(0)
    if PROMPT not in words or "only spaces" not in words or SENTENCE not in words:
        found.append(
            "step 22 does not say the browser stops an empty box and the page refuses spaces"
        )
    if "Leaving either box empty is refused" in words:
        found.append("step 22 says an empty box is refused by the page")
    row = next((line for line in text.splitlines() if line.startswith(f'| "{SENTENCE[:-1]}')), "")
    if "only spaces" not in row or PROMPT not in row:
        found.append(
            "the failure table's row does not say the sentence is for a box of only spaces"
        )
    return found


def test_the_guide_says_what_the_page_does():
    assert guide_problems(GUIDE.read_text(encoding="utf-8")) == []


OLD_STEP = (
    '22. Answer the question. Leaving either box empty is refused, for example with "'
    + SENTENCE
    + '", and the form keeps what you typed.'
)
NEW_STEP = (
    "22. Answer the question. Leaving either box completely empty stops the form in the browser, "
    f'which shows its own prompt, "{PROMPT}", and sends nothing. A box holding only spaces is '
    f'sent, and the page refuses it with "{SENTENCE}", and the form keeps what you typed.'
)
OLD_ROW = f'| "{SENTENCE}" or "Write the assumption in your own words." | The answer is empty. |'
NEW_ROW = (
    f'| "{SENTENCE}" or "Write the assumption in your own words." | The box holds only spaces. '
    f'A box left completely empty is stopped by the browser with "{PROMPT}" |'
)


def test_the_checker_finds_the_old_sentences_and_accepts_the_new_ones():
    assert len(guide_problems(OLD_STEP + "\n" + OLD_ROW)) == 3
    assert guide_problems(NEW_STEP + "\n" + NEW_ROW) == []
    assert guide_problems(NEW_STEP + "\n" + OLD_ROW) == [
        "the failure table's row does not say the sentence is for a box of only spaces"
    ]
    assert guide_problems(OLD_STEP + "\n" + NEW_ROW) != []


def test_a_planted_wrong_sentence_in_the_new_step_is_found():
    planted = NEW_STEP.replace("only spaces", "no letters")
    assert guide_problems(planted + "\n" + NEW_ROW) != []
