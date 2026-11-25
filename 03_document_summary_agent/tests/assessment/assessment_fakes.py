"""Fake judges for the engine's tests: answers built from the request, with no model call.

They live under a name no other test module in the topic uses: pytest puts every test folder on
the import path, and the first module of a name wins (``engine_fakes`` is the workflow tests' own).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Sequence

from assessment.records import (
    ClauseQuote,
    JudgementAnswer,
    JudgementRequest,
    PointJudgement,
    State,
)

_GAP = "The documents do not state all of what the provision requires."


def _words(text: str, count: int = 8) -> str:
    return " ".join(text.split()[:count])


def _bucket(obligation_id: str, label: str = "") -> int:
    digest = hashlib.sha256(f"{obligation_id}|{label}".encode()).digest()
    return digest[0] % 4


class ScriptedJudge:
    """Answers every request from its own first candidate, quoting it word for word.

    With ``mixed`` the states vary by a hash of the obligation, so every state and every gap path
    is met; without it every answer is covered. ``delay`` returns seconds to wait for a request,
    so the order calls finish in can be changed without changing any answer.
    """

    model_name = "fake-judge"

    def __init__(
        self,
        *,
        mixed: bool = True,
        delay: Callable[[JudgementRequest], float] | None = None,
    ) -> None:
        self.mixed = mixed
        self.delay = delay
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.in_flight = 0
        self.max_in_flight = 0

    def _state(self, request: JudgementRequest, label: str = "") -> State:
        if not self.mixed:
            return "covered"
        order: tuple[State, ...] = ("covered", "partly covered", "not covered", "in conflict")
        return order[_bucket(request.obligation_id, label)]

    async def __call__(
        self, request: JudgementRequest, *, faults: Sequence[str] = ()
    ) -> JudgementAnswer:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.calls.append((request.obligation_id, tuple(faults)))
        try:
            await asyncio.sleep(self.delay(request) if self.delay else 0)
            return self._answer(request)
        finally:
            self.in_flight -= 1

    def _answer(self, request: JudgementRequest) -> JudgementAnswer:
        first = request.candidates[0]
        quote = ClauseQuote(clause=first.clause, quote=_words(first.text))

        def part(label: str, state: State) -> PointJudgement:
            return PointJudgement(
                point=label,
                state=state,
                clause_quotes=[] if state == "not covered" else [quote],
                gap=None if state == "covered" else f"Point ({label}) {_GAP[4:]}",
            )

        state = self._state(request)
        points = [part(p, self._state(request, p)) for p in request.points]
        quotes = [] if state == "not covered" and not points else [quote]
        return JudgementAnswer(
            obligation_id=request.obligation_id,
            state=state,
            provision_quote=_words(request.provision_words),
            clause_quotes=quotes,
            gap=None if state == "covered" else _GAP,
            suggested_wording=None if state == "covered" else "The owner may add a clause.",
            points=points,
            reason="Scripted answer for a test.",
        )


class FlakyJudge(ScriptedJudge):
    """Answers wrongly on the first try for each obligation and rightly when asked again."""

    def _answer(self, request: JudgementRequest) -> JudgementAnswer:
        good = super()._answer(request)
        tries = sum(1 for o, _ in self.calls if o == request.obligation_id)
        if tries > 1:
            return good
        bad = [
            ClauseQuote(clause=q.clause, quote=q.quote + " and every other rule")
            for q in (
                good.clause_quotes or [ClauseQuote(clause=request.candidates[0].clause, quote="x")]
            )
        ]
        return good.model_copy(update={"clause_quotes": bad, "state": "covered", "points": []})


class AlwaysBadJudge(ScriptedJudge):
    """Always quotes words that are in no clause."""

    def _answer(self, request: JudgementRequest) -> JudgementAnswer:
        good = super()._answer(request)
        bad = [ClauseQuote(clause=request.candidates[0].clause, quote="words found in no clause")]
        return good.model_copy(update={"clause_quotes": bad, "state": "covered", "points": []})


_INIT = {
    "type": "system",
    "subtype": "init",
    "cwd": "/tmp/fsi-model-test",
    "model": "claude-sonnet-5-5",
    "tools": ["StructuredOutput"],
    "mcp_servers": [],
    "plugins": [],
    "slash_commands": [],
    "skills": [],
    "agents": [],
    "apiKeySource": "none",
    "claude_code_version": "2.1.302",
}


class StandInClaude:
    """Stands in for the headless process: answers each call with a tool call carrying an answer.

    It reads the obligation's id from the user message and returns the answer ``answers`` holds
    for it, so the record and replay of the real adapter run on the engine with no process.
    """

    def __init__(self, answers: dict[str, JudgementAnswer]) -> None:
        self.answers = answers
        self.calls: list[tuple[list[str], str]] = []

    def _raw(self, argv: list[str], stdin: str):
        import json
        import re

        from fsi_common.model.headless import RawRun

        self.calls.append((list(argv), stdin))
        found = re.search(r"Obligation: (.+?) \(", stdin)
        assert found, "the user message names its obligation"
        answer = self.answers[found.group(1)]
        payload = {
            "content": "",
            "tool_calls": [{"name": "JudgementAnswer", "args": answer.model_dump(mode="json")}],
        }
        events = [
            _INIT,
            {"type": "assistant", "message": {"content": [{"type": "text", "text": ""}]}},
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "",
                "num_turns": 1,
                "duration_ms": 1,
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": 10,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "output_tokens": 7,
                },
                "total_cost_usd": 0.0,
                "structured_output": payload,
            },
        ]
        return RawRun(0, "\n".join(json.dumps(e) for e in events) + "\n", "")

    def run(self, argv, *, stdin, env, cwd, timeout):
        return self._raw(argv, stdin)

    async def arun(self, argv, *, stdin, env, cwd, timeout):
        await asyncio.sleep(0)
        return self._raw(argv, stdin)
