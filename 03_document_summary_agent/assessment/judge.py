"""The judgement step: one request per applicable obligation, one model call, plain-code checks.

The request holds only what the obligation and its kept candidates give, in a fixed order, so a
replay matches whatever order the calls finish in. The call goes through ``get_model("assess")``
on its async path, and the answer is checked by code before any part of it is used.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from assessment.candidates import stems_of
from assessment.graph import defined_terms
from assessment.interfaces import JUDGE_ROLE, PROMPT_VERSION
from assessment.provisions import derive_state
from assessment.records import (
    BundleIndex,
    Candidate,
    CandidateText,
    JudgementAnswer,
    JudgementRequest,
    Obligation,
    State,
)
from assessment.texts import TextIndex
from assessment.validate import COMPLIANCE_WORDS
from context.errors import ContextError
from fsi_common.ids import digest_json
from utils.models import ROLE_MODELS, get_model

INSTRUCTIONS_PATH = Path(__file__).with_name("assess_instructions.md")


class JudgeReplyError(ContextError):
    """The model's reply is not a judgement answer; the message names the obligation."""


class AsyncJudge(Protocol):
    """What the engine calls for each obligation: an async judge that is told what was refused."""

    model_name: str

    async def __call__(
        self, request: JudgementRequest, *, faults: Sequence[str] = ()
    ) -> JudgementAnswer:
        """Return the answer to one request; ``faults`` lists what an earlier answer failed on."""
        ...


def load_instructions() -> str:
    """Return the judgement's instructions, the system message of every call.

    Returns:
        The text of ``assess_instructions.md``.
    """
    return INSTRUCTIONS_PATH.read_text(encoding="utf-8")


def digest_of(text: str) -> str:
    """Return the sha256 digest of instructions, as ``sha256:`` and 64 hex characters.

    Args:
        text: The instructions' text.

    Returns:
        The digest of the text's UTF-8 bytes, which are the file's bytes.
    """
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def recorded_instructions_digest(index: BundleIndex) -> str | None:
    """Read back the digest of the instructions a bundle's calls were made under.

    Args:
        index: The bundle's index.

    Returns:
        The digest, or ``None`` for a bundle made before it was recorded.
    """
    return index.instructions_digest


def definitions(texts: TextIndex) -> dict[str, str]:
    """List every term the corpus defines, with the words of its definition.

    Args:
        texts: The corpus.

    Returns:
        Each defined term and the text of the clause that defines it.
    """
    found = defined_terms(texts.clauses, in_force={d for d in texts.clauses if texts.in_force(d)})
    return {term: texts.clause_text(doc, number) or "" for term, (doc, number) in found.items()}


def _order(texts: TextIndex, candidate: Candidate) -> tuple[int, tuple[int, ...]]:
    documents = list(texts.clauses)
    number = tuple(int(p) for p in candidate.clause.clause.split("."))
    return documents.index(candidate.clause.document), number


def make_request(
    obligation: Obligation,
    kept: Sequence[Candidate],
    texts: TextIndex,
    terms: Mapping[str, str] | None = None,
) -> JudgementRequest:
    """Build the request of one obligation from its kept candidates.

    Args:
        obligation: The obligation.
        kept: Its kept candidates, in any order; they are put in the corpus's order.
        texts: The corpus, for each clause's words, version and standing.
        terms: Every defined term with its definition, from ``definitions``; read from the
            corpus when not given.

    Returns:
        The request, which depends on the obligation and its candidates alone.
    """
    known = dict(terms) if terms is not None else definitions(texts)
    used = stems_of(obligation.provision_words)
    texts_of: list[CandidateText] = []
    for candidate in sorted(kept, key=lambda c: _order(texts, c)):
        document, number = candidate.clause.document, candidate.clause.clause
        entry = texts.corpus.document(document)
        clause = next(c for c in texts.clauses[document] if c.number == number)
        version = (texts.control(document, "version") or "").removeprefix("Version:").strip()
        texts_of.append(
            CandidateText(
                clause=candidate.clause,
                document_title=entry.entry.title if entry else document,
                version=version or "unstated",
                in_force=texts.in_force(document),
                heading=clause.heading,
                text=clause.text,
            )
        )
    wanted = {
        term: text for term, text in known.items() if stems_of(term) and stems_of(term) <= used
    }
    return JudgementRequest(
        obligation_id=obligation.obligation_id,
        label=obligation.label,
        provision_words=obligation.provision_words,
        points=list(obligation.points),
        applies_to=list(obligation.applies_to),
        candidates=texts_of,
        defined_terms=dict(sorted(wanted.items())),
        prompt_version=PROMPT_VERSION,
    )


def request_digest(request: JudgementRequest) -> str:
    """Return the digest of a request's JSON, the key a run is recorded and replayed under.

    Args:
        request: The request.

    Returns:
        ``sha256:`` and 64 hex characters.
    """
    return digest_json(request.model_dump(mode="json"))


def render_request(request: JudgementRequest) -> str:
    """Write a request as the user message of the call.

    Args:
        request: The request.

    Returns:
        The provision, its points, the defined terms and each clause, in the request's order.
    """
    lines = [
        f"Obligation: {request.obligation_id} ({request.label})",
        f"Applies to: {', '.join(request.applies_to) or 'no entity named'}",
        "",
        "Words of the provision:",
        request.provision_words,
        "",
        "Points: " + (", ".join(request.points) if request.points else "none"),
    ]
    if request.defined_terms:
        lines += ["", "Defined terms the provision uses:"]
        lines += [f'- "{term}": {text}' for term, text in request.defined_terms.items()]
    lines += ["", "Clauses found for it, all in documents in force:"]
    for c in request.candidates:
        lines += [
            "",
            f"[{c.clause.document} clause {c.clause.clause}] {c.document_title}, version "
            f'{c.version}, section "{c.heading}"',
            c.text,
        ]
    return "\n".join(lines)


def check_answer(
    answer: JudgementAnswer,
    request: JudgementRequest,
    obligation: Obligation,
    texts: TextIndex,
) -> list[str]:
    """Check an answer by code, before any part of it is used.

    Args:
        answer: The model's answer.
        request: The request it answers.
        obligation: The obligation.
        texts: The regulations and the corpus.

    Returns:
        Each fault as ``<check name>: <where>``; empty when the answer holds.
    """
    faults: list[str] = []
    given = {(c.clause.document, c.clause.clause) for c in request.candidates}
    if answer.obligation_id != request.obligation_id:
        faults.append(f"wrong-obligation: answered {answer.obligation_id}")
    if not texts.provision_has(obligation.regulation, obligation.anchor, answer.provision_quote):
        faults.append(f"provision-quote-not-verbatim: {answer.provision_quote[:80]}")

    def check_quotes(quotes, where: str) -> None:
        for q in quotes:
            key = (q.clause.document, q.clause.clause)
            place = f"{key[0]} {key[1]}{where}"
            if key not in given:
                faults.append(f"clause-not-given: {place}")
            elif not texts.clause_has(key[0], key[1], q.quote):
                faults.append(f"clause-quote-not-verbatim: {place}: {q.quote[:80]}")

    check_quotes(answer.clause_quotes, "")
    if obligation.points:
        if sorted(p.point for p in answer.points) != sorted(obligation.points):
            faults.append(
                f"points-incomplete: gave {[p.point for p in answer.points]}, "
                f"the provision has {obligation.points}"
            )
        for p in answer.points:
            check_quotes(p.clause_quotes, f" (point {p.point})")
            if p.state != "not covered" and not p.clause_quotes:
                faults.append(f"state-without-clause: point {p.point} is {p.state}")
            if p.state != "covered" and not (p.gap or "").strip():
                faults.append(f"gap-missing: point {p.point}")
            if COMPLIANCE_WORDS.search(p.gap or ""):
                faults.append(f"compliance-words: gap of point {p.point}")
        state: State = (
            derive_state(p.state for p in answer.points) if answer.points else answer.state
        )
        quoted = bool(answer.clause_quotes or any(p.clause_quotes for p in answer.points))
    else:
        state = answer.state
        quoted = bool(answer.clause_quotes)
        if answer.points:
            faults.append("points-incomplete: points given for a provision with none")
    if state != "not covered" and not quoted:
        faults.append(f"state-without-clause: {state} and no clause quoted")
    if state != "covered" and not (answer.gap or "").strip() and not obligation.points:
        faults.append(f"gap-missing: state {state}")
    for name in ("gap", "suggested_wording", "reason"):
        if COMPLIANCE_WORDS.search(getattr(answer, name) or ""):
            faults.append(f"compliance-words: {name}")
    return faults


class ModelJudge:
    """Asks the ``assess`` role's model, on its async path, for one obligation's answer.

    The instructions are read once, when the judge is built, so every call of a run is made under
    the same text, whose digest is ``instructions_digest``.
    """

    def __init__(self, models: Callable[[str], BaseChatModel] | None = None) -> None:
        self._models = models or get_model
        self._instructions = load_instructions()
        self.instructions_digest = digest_of(self._instructions)

    @property
    def model_name(self) -> str:
        """The model the role runs on, as ``utils.models`` names it."""
        role = ROLE_MODELS.get(JUDGE_ROLE)
        return role.model if role else JUDGE_ROLE

    async def __call__(
        self, request: JudgementRequest, *, faults: Sequence[str] = ()
    ) -> JudgementAnswer:
        """Ask for the answer to one request.

        Args:
            request: The request.
            faults: What an earlier answer to this request was refused for; empty at the first
                try. The same faults and the same request give the same message, so a retry
                replays too.

        Returns:
            The answer, not yet checked.

        Raises:
            JudgeReplyError: If the reply is not a judgement answer.
        """
        message = render_request(request)
        if faults:
            listed = "\n".join(f"- {f}" for f in faults)
            message += (
                "\n\nYour earlier answer to this request was refused for these reasons:\n"
                f"{listed}\nAnswer again and put each of them right."
            )
        chat = self._models(JUDGE_ROLE).with_structured_output(JudgementAnswer)
        reply = await chat.ainvoke([SystemMessage(self._instructions), HumanMessage(message)])
        if isinstance(reply, JudgementAnswer):
            return reply
        try:
            return JudgementAnswer.model_validate(reply)
        except ValueError as exc:
            raise JudgeReplyError(
                f"The model's reply for {request.obligation_id} is not a judgement answer: {exc}"
            ) from exc
