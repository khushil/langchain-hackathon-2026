"""The review as the pages show it: what is settled, what still needs a person, and the answer.

One ``ReviewModel`` is built from the request and the decisions held so far. The page's sentence,
its tiles and every badge read it, so they cannot disagree.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from fsi_common.app.pages import Answer, Tile
from fsi_common.ids import digest_json
from fsi_common.records import Decision, OpenQuestion, Person
from fsi_common.records.questions import SETTLED_STATES
from review_app.drafts import Draft
from review_app.wording import decision_line
from utils.kyc_state import CitedFact, ReviewRequest

FactKind = Literal["yours", "carried", "needs"]
QuestionKind = Literal["answered", "assumed", "settled", "open"]


@dataclass(frozen=True)
class FactState:
    """Where one proposal stands: decided by the reviewer, carried from earlier, or waiting."""

    kind: FactKind
    decision: Decision | None
    differences: tuple[str, ...] = ()

    @property
    def settled(self) -> bool:
        """Whether no further decision is needed on this proposal."""
        return self.kind != "needs"

    @property
    def rejected(self) -> bool:
        """Whether the deciding decision is a rejection."""
        return self.decision is not None and self.settled and self.decision.outcome == "reject"


@dataclass(frozen=True)
class QuestionState:
    """Where one open question stands."""

    question: OpenQuestion
    kind: QuestionKind
    decision: Decision | None = None
    assumption: str | None = None

    @property
    def settled(self) -> bool:
        """Whether the question is answered, assumed or already settled."""
        return self.kind != "open"


def plural(count: int, one: str, many: str | None = None) -> str:
    """Write a count with its noun: ``1 proposal``, ``2 proposals``."""
    return f"{count} {one if count == 1 else many or one + 's'}"


class ReviewModel:
    """The batch put to the reviewer, with what is decided on it so far."""

    def __init__(
        self,
        request: ReviewRequest,
        draft: Draft,
        *,
        viewer: Person | None,
        earlier: Mapping[str, Decision] | None = None,
    ) -> None:
        self.request = request
        self.viewer = viewer
        self.earlier = dict(earlier or {})
        self.cited: dict[str, CitedFact] = {}
        for statement in request.statements:
            for cited in statement.facts:
                self.cited.setdefault(cited.fact.id, cited)
        self.proposals = {f: c for f, c in self.cited.items() if c.fact.kind == "proposal"}
        self._draft_facts = self.valid_fact_decisions(draft)
        self.fact_states = {f: self._fact_state(c) for f, c in self.proposals.items()}
        self._draft_answers = self.valid_answers(draft)
        self._draft_assumptions = self.valid_assumptions(draft)
        self.question_states = [self._question_state(q) for q in request.open_questions]

    def valid_fact_decisions(self, draft: Draft) -> dict[str, Decision]:
        """Return the viewer's held decisions that still describe the proposals as they now are."""
        return {
            fid: decision
            for fid, decision in draft.facts.items()
            if self._is_the_viewers(decision)
            and fid in self.proposals
            and decision.judged_digest == digest_json(self.proposals[fid].fact.judged_basis())
        }

    def _is_the_viewers(self, decision: Decision) -> bool:
        return self.viewer is not None and decision.reviewer == self.viewer

    def valid_answers(self, draft: Draft) -> dict[str, Decision]:
        """Return the viewer's held answers to questions that are still on the batch."""
        ids = {q.id for q in self.request.open_questions}
        return {
            qid: d for qid, d in draft.answers.items() if qid in ids and self._is_the_viewers(d)
        }

    def valid_assumptions(self, draft: Draft) -> dict[str, str]:
        """Return the held assumptions for questions that are still on the batch."""
        ids = {q.id for q in self.request.open_questions}
        return {qid: w for qid, w in draft.assumptions.items() if qid in ids}

    def _fact_state(self, cited: CitedFact) -> FactState:
        mine = self._draft_facts.get(cited.fact.id)
        if mine is not None:
            return FactState("yours", mine)
        if cited.carry.outcome == "carried":
            return FactState("carried", cited.carry.decision)
        return FactState("needs", cited.carry.decision, tuple(cited.carry.differences))

    def _question_state(self, question: OpenQuestion) -> QuestionState:
        if question.id in self._draft_answers:
            return QuestionState(question, "answered", self._draft_answers[question.id])
        if question.id in self._draft_assumptions:
            return QuestionState(question, "assumed", None, self._draft_assumptions[question.id])
        if question.state in SETTLED_STATES:
            return QuestionState(question, "settled", self.earlier.get(question.decision_id or ""))
        return QuestionState(question, "open")

    def question_state(self, question_id: str) -> QuestionState | None:
        """Return the state of one question, or None when the batch does not carry it."""
        return next((s for s in self.question_states if s.question.id == question_id), None)

    @property
    def facts_waiting(self) -> list[CitedFact]:
        """The proposals that still need a decision, in the order the batch holds them."""
        return [self.proposals[f] for f, s in self.fact_states.items() if not s.settled]

    @property
    def questions_waiting(self) -> list[OpenQuestion]:
        """The open questions that are neither answered nor accepted as assumptions."""
        return [s.question for s in self.question_states if not s.settled]

    @property
    def rejected_facts(self) -> list[CitedFact]:
        """The proposals the reviewer has rejected."""
        return [self.proposals[f] for f, s in self.fact_states.items() if s.rejected]

    def settled_questions(self) -> dict[str, str]:
        """Say how each question a person has settled was settled, by question id."""
        found: dict[str, str] = {}
        for state in self.question_states:
            if state.kind == "answered" and state.decision is not None:
                found[state.question.id] = decision_line(state.decision, self.viewer)
            elif state.kind == "assumed":
                found[state.question.id] = "Accepted by you as an assumption"
            elif state.kind == "settled":
                found[state.question.id] = (
                    decision_line(state.decision, self.viewer)
                    if state.decision is not None
                    else "Answered in an earlier review"
                )
        return found

    def cannot_sign_because(self) -> str | None:
        """Say in words why the batch cannot be signed yet, or return None when it can."""
        waiting, open_questions = self.facts_waiting, self.questions_waiting
        if waiting or open_questions:
            parts = []
            if waiting:
                parts.append(f"{plural(len(waiting), 'proposal')} without a decision")
            if open_questions:
                parts.append(f"{plural(len(open_questions), 'question')} not answered or accepted")
            return "The batch cannot be signed yet: " + " and ".join(parts) + "."
        if self.rejected_facts:
            return (
                f"You rejected {plural(len(self.rejected_facts), 'proposal')}. "
                "Amend it in your own words, or return the batch so that it can be read again."
            )
        return None

    def answer(self, entries: int) -> Answer:
        """Build the page's sentence and tiles from the same counts.

        Args:
            entries: The number of list entries each application was set against.
        """
        applications = len(self.proposals)
        settled_by_checks = sum(bool(c.fact.attributes["settled"]) for c in self.proposals.values())
        decided = sum(s.settled for s in self.fact_states.values())
        questions = len(self.question_states)
        questions_settled = sum(s.settled for s in self.question_states)
        waiting_facts, waiting_questions = applications - decided, questions - questions_settled
        head = (
            f"{plural(applications, 'application')} {'was' if applications == 1 else 'were'} "
            f"screened against {plural(entries, 'list entry', 'list entries')}: "
            f"{settled_by_checks} settled by the checks and "
            f"{applications - settled_by_checks} for a person to settle."
        )
        if waiting_facts or waiting_questions:
            needs = []
            if waiting_facts:
                needs.append(plural(waiting_facts, "proposal"))
            if waiting_questions:
                needs.append(plural(waiting_questions, "question"))
            verb = "needs" if waiting_facts + waiting_questions == 1 else "need"
            sentence = (
                f"{head} {' and '.join(needs)} still {verb} your decision before it is signed."
            )
        elif self.rejected_facts:
            sentence = (
                f"{head} You rejected {plural(len(self.rejected_facts), 'proposal')}, so the batch "
                "can be returned but not signed."
            )
        else:
            sentence = f"{head} Every proposal and question is settled, so it is ready to sign."
        return Answer(
            sentence=sentence,
            tiles=(
                Tile("Applications", str(applications)),
                Tile(
                    "Proposals decided",
                    f"{decided} of {applications}",
                    "needs_person" if waiting_facts else "normal",
                ),
                Tile(
                    "Questions settled",
                    f"{questions_settled} of {questions}",
                    "needs_person" if waiting_questions else "normal",
                ),
            ),
        )
