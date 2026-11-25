"""The judgement step: the request, the call through the ``assess`` role, the code checks."""

from __future__ import annotations

import asyncio

import pytest
from assessment.candidates import find_candidates
from assessment.graph import build_graph
from assessment.interfaces import JUDGE_ROLE, PROMPT_VERSION
from assessment.judge import (
    JudgeReplyError,
    ModelJudge,
    check_answer,
    definitions,
    load_instructions,
    make_request,
    render_request,
    request_digest,
)
from assessment.profile import load_profile
from assessment.records import ClauseQuote, JudgementAnswer, PointJudgement
from assessment.register import build_register
from assessment.validate import COMPLIANCE_WORDS
from assessment_fakes import ScriptedJudge

from fsi_common.model.errors import ReplayMissError
from utils import models as model_module


@pytest.fixture(scope="module")
def setup(texts):
    register = build_register(texts, load_profile("harbour-mutual-bank"))
    graph = build_graph(texts)
    candidates = find_candidates(register, texts, graph, second_look=False)
    terms = definitions(texts)
    return register, candidates, terms


def _with_points(setup, texts, *, want_points: bool):
    register, candidates, terms = setup
    kept = {}
    for c in candidates:
        if c.kept:
            kept.setdefault(c.obligation_id, []).append(c)
    for o in register.obligations:
        if o.applies is True and bool(o.points) == want_points and o.obligation_id in kept:
            return o, make_request(o, kept[o.obligation_id], texts, terms)
    raise AssertionError("no such obligation")


@pytest.fixture(scope="module")
def plain(setup, texts):
    return _with_points(setup, texts, want_points=False)


@pytest.fixture(scope="module")
def pointed(setup, texts):
    return _with_points(setup, texts, want_points=True)


def _answer(request, **update):
    judge = ScriptedJudge(mixed=False)
    answer = asyncio.run(judge(request))
    return answer.model_copy(update=update) if update else answer


def test_the_request_carries_the_provision_the_points_and_every_kept_clause(plain, pointed, texts):
    obligation, request = pointed
    assert request.obligation_id == obligation.obligation_id
    assert request.points == obligation.points
    assert request.provision_words == obligation.provision_words
    assert request.prompt_version == PROMPT_VERSION
    assert request.candidates and all(c.in_force for c in request.candidates)
    first = request.candidates[0]
    assert first.text == texts.clause_text(first.clause.document, first.clause.clause)
    assert first.version and first.document_title


def test_the_request_digest_is_stable_and_changes_with_the_request(plain):
    _, request = plain
    assert request_digest(request) == request_digest(request.model_copy())
    other = request.model_copy(update={"label": request.label + " changed"})
    assert request_digest(other) != request_digest(request)


def test_the_rendered_request_names_every_clause_by_document_and_number(plain):
    _, request = plain
    text = render_request(request)
    for c in request.candidates:
        assert f"{c.clause.document} clause {c.clause.clause}" in text
        assert c.text in text
    assert request.obligation_id in text


def test_a_correct_answer_has_no_fault(plain, pointed, texts):
    for obligation, request in (plain, pointed):
        assert check_answer(_answer(request), request, obligation, texts) == []


def test_a_provision_quote_not_in_the_provision_is_refused(plain, texts):
    obligation, request = plain
    answer = _answer(request, provision_quote="words the provision never states")
    faults = check_answer(answer, request, obligation, texts)
    assert any(f.startswith("provision-quote-not-verbatim") for f in faults), faults


def test_a_clause_quote_not_in_the_clause_is_refused(plain, texts):
    obligation, request = plain
    first = request.candidates[0]
    bad = ClauseQuote(clause=first.clause, quote="words found in no clause")
    faults = check_answer(_answer(request, clause_quotes=[bad]), request, obligation, texts)
    assert any(f.startswith("clause-quote-not-verbatim") for f in faults), faults


def test_a_clause_that_was_not_given_is_refused(plain, texts):
    obligation, request = plain
    given = {(c.clause.document, c.clause.clause) for c in request.candidates}
    other = next(
        (d, c.number)
        for d, cl in texts.clauses.items()
        if texts.in_force(d)
        for c in cl
        if (d, c.number) not in given
    )
    from assessment.records import ClauseRef

    quote = ClauseQuote(
        clause=ClauseRef(document=other[0], clause=other[1]),
        quote=" ".join(texts.clause_text(*other).split()[:6]),
    )
    faults = check_answer(_answer(request, clause_quotes=[quote]), request, obligation, texts)
    assert any(f.startswith("clause-not-given") for f in faults), faults


def test_the_words_of_compliance_are_refused_in_every_text_field(plain, texts):
    obligation, request = plain
    for field in ("gap", "suggested_wording", "reason"):
        answer = _answer(request, state="partly covered", gap="Some words are missing.")
        answer = answer.model_copy(update={field: "The Bank does not comply with it."})
        faults = check_answer(answer, request, obligation, texts)
        assert any(f.startswith("compliance-words") for f in faults), (field, faults)


def test_a_state_other_than_covered_needs_a_gap_and_a_state_other_than_not_covered_a_clause(
    plain, texts
):
    obligation, request = plain
    faults = check_answer(
        _answer(request, state="partly covered", gap=None), request, obligation, texts
    )
    assert any(f.startswith("gap-missing") for f in faults), faults
    faults = check_answer(_answer(request, clause_quotes=[]), request, obligation, texts)
    assert any(f.startswith("state-without-clause") for f in faults), faults


def test_the_points_of_the_answer_must_be_the_points_of_the_provision(pointed, texts):
    obligation, request = pointed
    answer = _answer(request)
    short = answer.model_copy(update={"points": answer.points[:-1]})
    faults = check_answer(short, request, obligation, texts)
    assert any(f.startswith("points-incomplete") for f in faults), faults
    renamed = [PointJudgement(**{**p.model_dump(), "point": "zz"}) for p in answer.points]
    faults = check_answer(answer.model_copy(update={"points": renamed}), request, obligation, texts)
    assert any(f.startswith("points-incomplete") for f in faults), faults


def test_an_answer_for_another_obligation_is_refused(plain, texts):
    obligation, request = plain
    answer = _answer(request, obligation_id="DORA art:1/1")
    faults = check_answer(answer, request, obligation, texts)
    assert any(f.startswith("wrong-obligation") for f in faults), faults


class _Runnable:
    def __init__(self, owner):
        self.owner = owner

    async def ainvoke(self, messages):
        self.owner.messages = messages
        return self.owner.reply


class _Chat:
    def __init__(self, reply):
        self.reply = reply
        self.schema = None
        self.messages = None

    def with_structured_output(self, schema, **kwargs):
        self.schema = schema
        return _Runnable(self)


def test_the_model_judge_asks_the_assess_role_through_the_async_path(plain):
    _, request = plain
    answer = _answer(request)
    chat = _Chat(answer)
    roles = []

    def models(role):
        roles.append(role)
        return chat

    judge = ModelJudge(models)
    got = asyncio.run(judge(request))
    assert got == answer
    assert roles == [JUDGE_ROLE] == ["assess"]
    assert chat.schema is JudgementAnswer
    system, human = chat.messages
    assert system.content == load_instructions()
    assert render_request(request) in human.content
    assert "refused" not in human.content


def test_a_retry_tells_the_model_what_was_refused(plain):
    _, request = plain
    chat = _Chat(_answer(request))
    asyncio.run(ModelJudge(lambda role: chat)(request, faults=["clause-quote-not-verbatim: x 1.1"]))
    assert "clause-quote-not-verbatim: x 1.1" in chat.messages[1].content


def test_a_reply_that_is_not_an_answer_is_an_error_naming_the_obligation(plain):
    _, request = plain
    with pytest.raises(JudgeReplyError, match=request.obligation_id):
        asyncio.run(ModelJudge(lambda role: _Chat({"state": "nonsense"}))(request))


def test_the_model_judge_on_the_real_adapter_in_replay_never_starts_a_call(
    plain, monkeypatch, tmp_path
):
    _, request = plain
    monkeypatch.setitem(
        model_module.ROLE_MODELS,
        "assess",
        model_module.RoleModel("claude-sonnet-5-5", "medium", "test"),
    )
    monkeypatch.setenv("MODEL_BACKEND", "replay")
    monkeypatch.setenv("MODEL_RECORDINGS_DIR", str(tmp_path))
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    with pytest.raises(ReplayMissError):
        asyncio.run(ModelJudge()(request))


def test_the_instructions_are_written_and_use_none_of_the_words_of_compliance():
    text = load_instructions()
    assert len(text.split()) > 300
    assert COMPLIANCE_WORDS.search(text) is None


def _with_first_point(answer, **update):
    first = answer.points[0].model_copy(update=update)
    return answer.model_copy(update={"points": [first, *answer.points[1:]]})


def test_a_point_quote_not_in_its_clause_is_refused_by_the_point(pointed, texts):
    obligation, request = pointed
    answer = _answer(request)
    given = answer.points[0].clause_quotes[0].clause
    bad = ClauseQuote(clause=given, quote="words found in no clause")
    answer = _with_first_point(answer, state="partly covered", clause_quotes=[bad], gap="Missing.")
    faults = check_answer(answer, request, obligation, texts)
    point = answer.points[0].point
    assert any(
        f.startswith("clause-quote-not-verbatim") and f"(point {point})" in f for f in faults
    ), faults


def test_the_words_of_compliance_in_a_point_gap_are_refused_by_the_point(pointed, texts):
    obligation, request = pointed
    answer = _with_first_point(
        _answer(request), state="partly covered", gap="The Bank does not comply with this point."
    )
    faults = check_answer(answer, request, obligation, texts)
    assert f"compliance-words: gap of point {answer.points[0].point}" in faults, faults


def test_the_instructions_are_read_once_when_the_judge_is_built(plain, tmp_path, monkeypatch):
    import hashlib

    from assessment import judge as judge_module

    _, request = plain
    path = tmp_path / "assess_instructions.md"
    path.write_text("First instructions.\n", encoding="utf-8")
    monkeypatch.setattr(judge_module, "INSTRUCTIONS_PATH", path)
    chat = _Chat(_answer(request))
    judge = ModelJudge(lambda role: chat)
    path.write_text("Edited while the run is going.\n", encoding="utf-8")
    asyncio.run(judge(request))
    assert chat.messages[0].content == "First instructions.\n"
    assert (
        judge.instructions_digest
        == "sha256:" + hashlib.sha256(b"First instructions.\n").hexdigest()
    )
