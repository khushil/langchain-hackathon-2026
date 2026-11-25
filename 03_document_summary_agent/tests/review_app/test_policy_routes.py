"""The policy pages over the fake bundle: every route renders, and only a person decides."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

import pytest
from assessment.bundle import write_bundle
from policy_pages_support import (
    BASE,
    CORPUS,
    DANA,
    LEFT_OUT_COMMANDS,
    LEFT_OUT_REASON,
    TODAY,
    make_app,
    text_of,
    with_a_loose_statement,
    write_fake,
    write_left_out,
)

from fsi_common.records import Person

ERIK = Person(name="Erik Lund", role="Head of Technology Risk")
GAP_WORDS = {
    "partly covered": "Partly covered",
    "not covered": "Not covered",
    "in conflict": "In conflict",
}
COMPLIANCE_CLAIM = re.compile(r"\bcompl(?:y|ies|iant|iance)\b", re.I)


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    root = tmp_path_factory.mktemp("bundles")
    bundle, folder = write_fake(root)
    return bundle, folder


@pytest.fixture()
def client(made):
    return make_app(made[1])[0]


@pytest.fixture()
def app(made):
    return make_app(made[1])


def main_of(html: str) -> str:
    """Return the page's own content: the top bar, which names the topic, is left out."""
    return re.search(r"<main.*?</main>", html, re.S).group(0)


def obligation_path(obligation_id: str) -> str:
    key, _, anchor = obligation_id.partition(" ")
    return f"{BASE}/obligations/{key}/{anchor}"


def gaps(bundle):
    return [a for a in bundle.assessments if a.state != "covered"]


def decide(client, bundle, assessment, **fields):
    body = {"assessment_id": assessment.id, "outcome": "accept", "reason": "Read both texts."}
    body.update(fields)
    return client.post(f"{obligation_path(assessment.obligation_id)}/decide", data=body)


def sign(client, bundle, **fields):
    body = {"brief_digest": bundle.gap_report.content_digest, "outcome": "signed"}
    body.update(fields)
    return client.post(f"{BASE}/gap-report/sign", data=body)


def test_every_page_of_the_contract_renders_from_the_fake_bundle(made, client):
    bundle, _ = made
    fixed = [
        BASE,
        f"{BASE}/register",
        f"{BASE}/register.csv",
        f"{BASE}/clauses",
        f"{BASE}/clauses.csv",
        f"{BASE}/graph",
        f"{BASE}/gap-report",
    ]
    applicable = [
        o.obligation_id for o in bundle.obligation_register.obligations if o.applies is True
    ]
    assert len(applicable) == 219
    for address in [*fixed, *(obligation_path(o) for o in applicable)]:
        reply = client.get(address)
        assert reply.status_code == 200, address
    assert len(fixed) + len(applicable) == 226


def test_the_picture_leads_the_policies_page_with_the_population_line(client):
    page = client.get(BASE).text
    assert page.index('data-hook="picture"') < page.index("<table")
    for line in (
        "101 of 219 DORA obligations apply",
        "21 of 422 AI Act obligations apply",
        "97 of 97 SS1/23 obligations apply",
    ):
        assert line in text_of(page), line
    assert text_of(page).index("101 of 219 DORA") < text_of(page).index("21 of 422 AI Act")


def test_an_unknown_corpus_an_unknown_obligation_and_an_obligation_that_does_not_apply_are_404(
    made, client
):
    bundle, _ = made
    assert client.get("/compliance-brief/policies/no-such-firm").status_code == 404
    assert client.get(f"{BASE}/obligations/DORA/art:99999").status_code == 404
    not_apply = next(o for o in bundle.obligation_register.obligations if o.applies is False)
    assert client.get(obligation_path(not_apply.obligation_id)).status_code == 404
    assert client.get("/compliance-brief/policies/..%2Fetc").status_code == 404


def test_no_policy_page_says_a_firm_complies_or_does_not(made, client):
    bundle, _ = made
    pages = [
        BASE,
        f"{BASE}/register",
        f"{BASE}/clauses",
        f"{BASE}/graph",
        f"{BASE}/gap-report",
        f"{BASE}/measures",
    ]
    pages += [obligation_path(a.obligation_id) for a in bundle.assessments]
    for address in pages:
        words = text_of(main_of(client.get(address).text)).replace(DANA.role, "")
        assert COMPLIANCE_CLAIM.search(words) is None, address


def test_a_decision_is_built_only_for_a_signed_in_person_and_nothing_is_kept_without_one(made):
    bundle, root = made
    client, records = make_app(root, signed_in=None)
    target = gaps(bundle)[0]
    reply = decide(client, bundle, target)
    assert reply.status_code == 403
    assert "Sign in with your name and role" in reply.text
    assert records.decisions(CORPUS) == {}
    page = client.get(obligation_path(target.obligation_id)).text
    assert 'data-hook="decision-form"' not in page


def test_accepting_records_the_signed_in_persons_decision_and_the_page_shows_it(made, app):
    bundle, _ = made
    client, records = app
    target = gaps(bundle)[0]
    reply = decide(client, bundle, target, reason="The clause covers the provision.")
    assert reply.status_code == 303
    assert reply.headers["location"] == obligation_path(target.obligation_id)
    held = records.decisions(CORPUS)[target.id]
    assert held.reviewer == DANA and held.outcome == "accept" and held.date == TODAY
    assert held.subject_id == target.id
    page = text_of(client.get(obligation_path(target.obligation_id)).text)
    assert "Accepted by you" in page and "The clause covers the provision." in page


def test_amending_needs_wording_and_a_reason_is_always_needed(made, app):
    bundle, _ = made
    client, records = app
    target = gaps(bundle)[0]
    empty_reason = decide(client, bundle, target, reason="  ")
    assert empty_reason.status_code == 422
    assert "Write your reason in your own words." in text_of(empty_reason.text)
    no_wording = decide(client, bundle, target, outcome="amend")
    assert no_wording.status_code == 422
    assert "Write the amended wording in your own words." in text_of(no_wording.text)
    bad = decide(client, bundle, target, outcome="approve")
    assert bad.status_code == 422 and "Choose accept, amend or reject." in text_of(bad.text)
    assert records.decisions(CORPUS) == {}
    ok = decide(client, bundle, target, outcome="amend", amendment="Clause 4.1 covers point (b).")
    assert ok.status_code == 303
    assert records.decisions(CORPUS)[target.id].amendment == "Clause 4.1 covers point (b)."


def test_a_decision_on_an_assessment_that_is_not_the_one_shown_is_refused(made, app):
    bundle, _ = made
    client, records = app
    target, other = gaps(bundle)[0], gaps(bundle)[1]
    reply = client.post(
        f"{obligation_path(target.obligation_id)}/decide",
        data={"assessment_id": other.id, "outcome": "accept", "reason": "Read it."},
    )
    assert reply.status_code == 409
    assert "changed after you opened it, so nothing was recorded" in text_of(reply.text)
    assert records.decisions(CORPUS) == {}


def test_a_decision_survives_a_restart_when_the_state_is_in_a_folder(made, tmp_path):
    bundle, root = made
    first, _ = make_app(root, state_dir=tmp_path)
    target = gaps(bundle)[0]
    assert decide(first, bundle, target).status_code == 303
    again, records = make_app(root, state_dir=tmp_path)
    assert records.decisions(CORPUS)[target.id].reviewer == DANA
    assert "Accepted by you" in text_of(again.get(obligation_path(target.obligation_id)).text)


def test_the_persons_words_are_escaped_on_the_page(made, app):
    bundle, _ = made
    client, _ = app
    target = gaps(bundle)[0]
    decide(client, bundle, target, reason="<script>x</script> because")
    page = client.get(obligation_path(target.obligation_id)).text
    assert "<script>x" not in page and "&lt;script&gt;x&lt;/script&gt;" in page


class _Submits(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_form = False
        self.found: list[tuple[str | None, str | None]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.in_form = a.get("data-hook") == "signoff-form"
        elif self.in_form and tag == "button" and a.get("type", "submit") == "submit":
            self.found.append((a.get("name"), a.get("value")))
        elif self.in_form and tag == "input" and a.get("type") in {"submit", "image"}:
            self.found.append((a.get("name"), a.get("value")))

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_form = False


def test_the_sign_off_form_holds_two_submit_buttons_to_sign_or_to_return_and_nothing_else(client):
    scan = _Submits()
    scan.feed(client.get(f"{BASE}/gap-report").text)
    assert scan.found == [("outcome", "signed"), ("outcome", "returned")]


def test_the_gap_report_cannot_be_signed_until_every_gap_is_decided_and_none_rejected(made, app):
    bundle, _ = made
    client, records = app
    refused = sign(client, bundle)
    assert refused.status_code == 422
    waiting = len(gaps(bundle))
    assert f"{waiting} gaps have no decision from you" in text_of(refused.text)
    assert records.sign_off(CORPUS, bundle.gap_report.id) is None
    for assessment in gaps(bundle):
        decide(client, bundle, assessment, outcome="reject", reason="Not what the clause says.")
    rejected = sign(client, bundle)
    assert rejected.status_code == 422 and "so the gap report can be returned" in text_of(
        rejected.text
    )
    for assessment in gaps(bundle):
        decide(client, bundle, assessment)
    done = sign(client, bundle)
    assert done.status_code == 303 and done.headers["location"] == f"{BASE}/gap-report"
    signed = records.sign_off(CORPUS, bundle.gap_report.id)
    assert signed.outcome == "signed" and signed.reviewer == DANA
    assert signed.brief_digest == bundle.gap_report.content_digest
    page = text_of(client.get(f"{BASE}/gap-report").text)
    assert "Dana Whitfield" in page and "Signed" in page


def test_a_signed_gap_report_refuses_a_later_decision_and_a_second_sign_off(made, app):
    bundle, _ = made
    client, records = app
    for assessment in gaps(bundle):
        decide(client, bundle, assessment)
    assert sign(client, bundle).status_code == 303
    later = decide(client, bundle, gaps(bundle)[0], outcome="reject", reason="Changed my mind.")
    assert later.status_code == 409 and "signed" in text_of(later.text)
    assert records.decisions(CORPUS)[gaps(bundle)[0].id].outcome == "accept"
    assert sign(client, bundle).status_code == 409


def test_a_return_needs_the_reason_and_leaves_the_decisions_open(made, app):
    bundle, _ = made
    client, records = app
    missing = sign(client, bundle, outcome="returned")
    assert missing.status_code == 422
    assert "Write why you are returning the gap report in your own words." in text_of(missing.text)
    done = sign(client, bundle, outcome="returned", reason="Needs the ICT policy read again.")
    assert done.status_code == 303
    assert records.sign_off(CORPUS, bundle.gap_report.id).outcome == "returned"
    assert decide(client, bundle, gaps(bundle)[0]).status_code == 303


def test_a_sign_off_posted_against_an_older_digest_is_refused_and_nobody_signs_without_signing_in(
    made,
):
    bundle, root = made
    client, records = make_app(root)
    stale = sign(client, bundle, brief_digest="sha256:" + "0" * 64)
    assert stale.status_code == 409 and "changed after you opened it" in text_of(stale.text)
    nobody, other = make_app(root, signed_in=None)
    assert sign(nobody, bundle).status_code == 403
    assert other.sign_off(CORPUS, bundle.gap_report.id) is None
    assert records.sign_off(CORPUS, bundle.gap_report.id) is None


def test_another_person_signs_for_themselves_and_the_record_names_them(made):
    bundle, root = made
    client, records = make_app(root, signed_in=ERIK)
    for assessment in gaps(bundle):
        decide(client, bundle, assessment)
    assert sign(client, bundle).status_code == 303
    assert records.sign_off(CORPUS, bundle.gap_report.id).reviewer == ERIK
    assert "Erik Lund" in text_of(client.get(f"{BASE}/gap-report").text)


def test_the_csv_exports_hold_every_row_in_the_order_shown(made, client):
    bundle, _ = made
    register = client.get(f"{BASE}/register.csv")
    assert register.headers["content-type"].startswith("text/csv")
    assert len(register.text.strip().splitlines()) == 1 + len(
        bundle.obligation_register.obligations
    )
    clauses = client.get(f"{BASE}/clauses.csv")
    assert len(clauses.text.strip().splitlines()) == 1 + len(bundle.clause_map)


def test_the_policy_pages_carry_the_demo_tag_and_no_method_page(client):
    for address in (BASE, f"{BASE}/register", f"{BASE}/gap-report"):
        page = client.get(address).text
        assert 'data-hook="demo-tag"' in page
        assert "not legal, compliance or regulatory advice" not in page.lower()
        assert "How this is worked out" not in page


def test_a_regulation_the_run_left_out_shows_as_one_line_with_its_reason_and_commands(tmp_path):
    _, root = write_left_out(tmp_path)
    client, _ = make_app(root)
    page = client.get(BASE).text
    words = text_of(main_of(page))
    assert f"SS1/23 is not included here: {LEFT_OUT_REASON}. To include it:" in words
    for command in LEFT_OUT_COMMANDS:
        assert command in words
    assert page.count('data-hook="not-included"') == 1


def test_nothing_of_a_regulation_left_out_is_counted_or_drawn_on_any_page(tmp_path):
    bundle, root = write_left_out(tmp_path)
    client, _ = make_app(root)
    pages = [BASE, f"{BASE}/register", f"{BASE}/clauses", f"{BASE}/graph", f"{BASE}/gap-report"]
    pages += [f"{BASE}/measures"]
    pages += [obligation_path(a.obligation_id) for a in bundle.assessments]
    for address in pages:
        reply = client.get(address)
        assert reply.status_code == 200, address
        words = text_of(main_of(reply.text))
        outside_the_line = re.sub(r"SS1/23 is not included here:.*?To include it:", "", words)
        outside_the_line = outside_the_line.replace(LEFT_OUT_COMMANDS[1], "")
        assert "SS1/23" not in outside_the_line and "SS1-23" not in outside_the_line, address
    picture = client.get(BASE).text
    assert 'data-regulation="SS1-23"' not in picture
    assert client.get(obligation_path("SS1-23 prin:5.1/a")).status_code == 404


def test_a_whole_run_shows_no_line_about_what_is_left_out(client):
    assert 'data-hook="not-included"' not in client.get(BASE).text


def test_the_measures_page_gives_four_figures_each_with_its_denominator(made, client):
    page = client.get(f"{BASE}/measures")
    assert page.status_code == 200
    words = text_of(main_of(page.text))
    for label in (
        "Seeded gaps found",
        "Covered seeds called a gap",
        "Citations that name no seeded clause",
        "Seeds found in the same state",
    ):
        assert label in words, label
    assert 'data-hook="measure"' in page.text and page.text.count('data-hook="measure"') == 4
    assert "Every finding is a proposal that a person decides." in words
    assert "partly covered" in words


def test_the_measures_page_is_a_tab_of_every_policy_page(client):
    for address in (BASE, f"{BASE}/register", f"{BASE}/gap-report", f"{BASE}/measures"):
        assert f'href="{BASE}/measures"' in client.get(address).text


def _with_run(root, run):
    import json

    index = root / CORPUS / "bundle.json"
    held = json.loads(index.read_text("utf-8"))
    held["run"] = run
    index.write_text(json.dumps(held), "utf-8")


def test_about_says_once_that_ss123_is_read_from_a_private_recording(tmp_path):
    from review_app.context import Services
    from review_app.routes_policies import PRIVATE_RECORDING, about_lines

    services = Services()
    _, root = write_fake(tmp_path)
    assert about_lines(services, root) == ()  # a fake run is no recording
    _with_run(root, "record")
    assert about_lines(services, root) == (PRIVATE_RECORDING,)
    assert PRIVATE_RECORDING == "SS1/23's assessment is read from a private recording."
    _with_run(root, "replay")
    assert about_lines(services, root) == (PRIVATE_RECORDING,)
    assert about_lines(services, tmp_path / "missing") == ()


def test_about_says_nothing_of_ss123_when_the_run_left_it_out(tmp_path):
    from review_app.context import Services
    from review_app.routes_policies import about_lines

    _, root = write_left_out(tmp_path)
    _with_run(root, "record")
    assert about_lines(Services(), root) == ()


def test_a_person_cannot_sign_the_gap_report_over_decisions_another_person_made(made, tmp_path):
    bundle, root = made
    dana, _ = make_app(root, state_dir=tmp_path)
    for assessment in gaps(bundle):
        assert decide(dana, bundle, assessment).status_code == 303
    erik, records = make_app(root, state_dir=tmp_path, signed_in=ERIK)
    words = (
        "Decisions on this gap report were made by Dana Whitfield, "
        f"{DANA.role}. Sign in as that person to sign it, or record your own decisions again."
    )
    assert words in text_of(erik.get(f"{BASE}/gap-report").text)
    refused = sign(erik, bundle)
    assert refused.status_code == 422 and words in text_of(refused.text)
    assert records.sign_off(CORPUS, bundle.gap_report.id) is None
    returned = sign(erik, bundle, outcome="returned", reason="Not mine to sign.")
    assert returned.status_code == 303


def test_a_statement_that_rests_on_no_assessment_is_named_and_the_sign_off_is_refused(tmp_path):
    bundle, root = write_fake(tmp_path / "bundles")
    loose = with_a_loose_statement(bundle)
    write_bundle(loose, root)
    client, records = make_app(root, state_dir=tmp_path / "state")
    for assessment in gaps(loose):
        decide(client, loose, assessment)
    page = text_of(client.get(f"{BASE}/gap-report").text)
    assert "A gap nobody assessed." in page and "rests on no assessment" in page
    refused = sign(client, loose)
    assert refused.status_code == 422 and "A gap nobody assessed." in text_of(refused.text)
    assert records.sign_off(CORPUS, loose.gap_report.id) is None


def test_the_measures_sentence_names_the_state_with_the_most_gaps_of_the_bundle(made, client):
    bundle, _ = made
    counts = {s: sum(a.state == s for a in bundle.assessments) for s in GAP_WORDS}
    largest = max(counts, key=counts.get)
    sentence = html.unescape(text_of(client.get(f"{BASE}/measures").text))
    assert f'"{GAP_WORDS[largest]}" is where the engine asks for a person most.' in sentence
    for other in set(GAP_WORDS) - {largest}:
        assert f'"{GAP_WORDS[other]}" is where the engine' not in sentence


def open_gap_link(client, address):
    """Return the address the page's link to the next gap without the person's decision gives."""
    found = re.search(r'data-hook="next-open-gap" href="([^"]+)"', client.get(address).text)
    return None if found is None else found.group(1)


def test_each_assessment_links_to_the_next_gap_without_the_persons_decision(made, tmp_path):
    bundle, root = made
    client, _ = make_app(root, state_dir=tmp_path)
    gap_paths = [obligation_path(a.obligation_id) for a in gaps(bundle)]
    assert "Next gap without your decision" in text_of(client.get(gap_paths[0]).text)
    assert open_gap_link(client, gap_paths[0]) == gap_paths[1]
    assert decide(client, bundle, gaps(bundle)[1]).status_code == 303
    assert open_gap_link(client, gap_paths[0]) == gap_paths[2]
    walked = [gap_paths[0]]
    while (following := open_gap_link(client, walked[-1])) is not None:
        walked.append(following)
        assert decide(client, bundle, gaps(bundle)[gap_paths.index(following)]).status_code == 303
    assert walked == [gap_paths[0], *gap_paths[2:], gap_paths[0]]
    assert "Next gap without your decision" not in text_of(client.get(gap_paths[0]).text)


def test_the_picture_links_once_to_the_first_gap_without_the_persons_decision(made, tmp_path):
    bundle, root = made
    client, _ = make_app(root, state_dir=tmp_path)
    page = client.get(BASE).text
    assert page.count('data-hook="first-open-gap"') == 1
    assert "First gap without your decision" in text_of(page)
    assert f'href="{obligation_path(gaps(bundle)[0].obligation_id)}"' in page
    for assessment in gaps(bundle):
        decide(client, bundle, assessment)
    assert 'data-hook="first-open-gap"' not in client.get(BASE).text
    other, _ = make_app(root, state_dir=tmp_path, signed_in=ERIK)
    assert 'data-hook="first-open-gap"' in other.get(BASE).text
    nobody, _ = make_app(root, state_dir=tmp_path, signed_in=None)
    assert 'data-hook="first-open-gap"' not in nobody.get(BASE).text


def test_a_signed_gap_report_has_no_link_to_a_gap_to_decide(made, app):
    bundle, _ = made
    client, _ = app
    for assessment in gaps(bundle):
        decide(client, bundle, assessment)
    assert sign(client, bundle).status_code == 303
    assert 'data-hook="first-open-gap"' not in client.get(BASE).text
    assert (
        'data-hook="next-open-gap"'
        not in client.get(obligation_path(gaps(bundle)[0].obligation_id)).text
    )
