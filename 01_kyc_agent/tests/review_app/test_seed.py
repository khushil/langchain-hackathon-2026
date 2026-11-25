"""The starting work: one batch waiting, one signed by the fictional reviewer through the routes."""

import json

import pytest
from kyc_fakes import ScriptedReader
from starlette.testclient import TestClient
from support import BASE, text_of

from fsi_common.app import AppConfig, SeedError, create_app
from fsi_common.app.session import SessionCodec
from fsi_common.records import Decision, SignOff
from review_app import seed, service
from review_app.context import Services
from review_app.plugin import NAME, build_plugin
from review_app.seed_fixture import DECISIONS, QUESTIONS


@pytest.fixture()
def scripted():
    service.use_models(ScriptedReader())
    yield
    service.use_models(None)


def make(tmp_path, scripted):
    services = Services()
    config = AppConfig(secret=b"s", topic_folders=(), state_dir=tmp_path, seed=NAME)
    app = create_app(config, topics=[build_plugin(services)])
    return services, app


def test_the_seed_makes_a_batch_waiting_and_a_batch_signed_by_the_fictional_reviewer(
    tmp_path, scripted
):
    services, app = make(tmp_path, scripted)
    runs = services.runs()
    threads = runs.list_runs()
    assert len(threads) == 2
    statuses = sorted(runs.status(t) for t in threads)
    assert statuses == ["awaiting_review", "signed"]
    signed = next(t for t in threads if runs.status(t) == "signed")
    state = runs.result(signed)
    sign_off = SignOff.model_validate(state["sign_off"])
    assert (sign_off.reviewer.name, sign_off.reviewer.role) == (
        "Dana Whitfield",
        "Head of Compliance",
    )
    assert sign_off.date == "2026-11-24" and sign_off.outcome == "signed"
    decisions = [Decision.model_validate(d) for d in state["decisions"].values()]
    assert {d.reviewer for d in decisions} == {sign_off.reviewer}
    assert len(decisions) == 25 + 14 - len(state["sign_off"]["assumptions"])
    assert len(sign_off.assumptions) == 2
    words = {d.reason for d in decisions}
    assert {d.reason for d in DECISIONS} <= words
    assert len(DECISIONS) == 25 and len({d.customer for d in DECISIONS}) == 25
    runs.close()
    services.drafts.close()


def test_the_seeded_batch_is_in_the_reviewers_hands_with_nothing_decided(tmp_path, scripted):
    services, app = make(tmp_path, scripted)
    runs = services.runs()
    waiting = next(t for t in runs.list_runs() if runs.status(t) == "awaiting_review")
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(app.state.cookie_name, SessionCodec(b"s").encode(seed.REVIEWER))
    page = text_of(client.get(f"{BASE}/runs/{waiting}/review").text)
    assert "25 applications were screened" in page
    assert "settled" in page
    runs.close()
    services.drafts.close()


def test_starting_twice_on_one_folder_adds_no_second_copy(tmp_path, scripted):
    services, _ = make(tmp_path, scripted)
    first = services.runs().list_runs()
    services.runs().close()
    services.drafts.close()
    again, _ = make(tmp_path, scripted)
    assert again.runs().list_runs() == first
    again.runs().close()
    again.drafts.close()


def test_a_folder_with_batches_and_no_marker_is_refused(tmp_path, scripted):
    services, _ = make(tmp_path, scripted)
    (tmp_path / seed.MARKER_FILE).unlink()
    services.runs().close()
    services.drafts.close()
    with pytest.raises(SeedError, match="did not make"):
        make(tmp_path, scripted)


def test_a_marker_made_from_another_fixture_is_refused(tmp_path, scripted):
    services, _ = make(tmp_path, scripted)
    (tmp_path / seed.MARKER_FILE).write_text(json.dumps({"seed": NAME, "digest": "sha256:x"}))
    services.runs().close()
    services.drafts.close()
    with pytest.raises(SeedError, match="did not make"):
        make(tmp_path, scripted)


def test_a_fixture_that_does_not_fit_the_batch_is_refused_naming_what_changed(monkeypatch):
    service.use_models(ScriptedReader())
    try:
        runs = service.make_runs()
        from support import start_run

        thread = start_run(runs)
        request = runs.review_request(thread)
        monkeypatch.setattr(seed, "DECISIONS", DECISIONS[1:])
        monkeypatch.setattr(seed, "QUESTIONS", QUESTIONS[:-1])
        with pytest.raises(SeedError, match=r"proposals with no decision in the seed.*CUST-001"):
            seed._check_fixture(request)
        with pytest.raises(SeedError, match="questions with no answer"):
            seed._check_fixture(request)
    finally:
        service.use_models(None)


def test_the_seed_builds_no_decision_itself_and_a_planted_builder_is_found():
    from test_structure import violations

    source = open(seed.__file__, encoding="utf-8").read()
    assert violations(source, "seed.py") == []
    planted = source + "\nfrom fsi_common.records import Decision\nDecision.on(None)\n"
    assert violations(planted, "seed.py")


def _edits(a: str, b: str) -> int:
    import difflib

    return sum(op[0] != "equal" for op in difflib.SequenceMatcher(None, a, b).get_opcodes())


def test_the_words_of_the_seed_about_a_spelling_hold_to_the_names():
    from kyc_fakes import NAMES

    from context.reader import entries_of

    entries = {e.anchor_part: e for e in entries_of()}
    said = 0
    for question in QUESTIONS:
        reason = question.reason or ""
        places = 2 if "in two places" in reason else 1 if "one letter" in reason else 0
        if places:
            said += 1
            name, entry = NAMES[question.customer], entries[question.place].name
            assert _edits(name.lower(), entry.lower()) == places, (question.customer, reason)
    assert said == 4
