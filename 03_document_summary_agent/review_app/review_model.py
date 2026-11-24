"""The review as the pages show it: what is settled, what still needs a person, and the answer.

One ``ReviewModel`` is built from the request and the decisions held so far. The page's sentence,
its tiles and every badge read it, so they cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fsi_common.app.pages import Answer, Tile
from fsi_common.ids import digest_json
from fsi_common.records import Decision, OpenQuestion, Person
from fsi_common.records.questions import SETTLED_STATES
from review_app.drafts import Draft
from utils.state import CitedFact, ReviewRequest

FactKind = Literal["yours", "carried", "needs"]
QuestionKind = Literal["answered", "assumed", "settled", "open"]


@dataclass(frozen=True)
class FactState:
    """Where one fact stands: decided by the reviewer, carried from earlier, or waiting."""

    kind: FactKind
    decision: Decision | None
    differences: tuple[str, ...] = ()

    @property
    def settled(self) -> bool:
        """Whether no further decision is needed on this fact."""
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


def _plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else many or one + 's'}"


class ReviewModel:
    """The brief put to the reviewer, with what is decided on it so far."""

    def __init__(
        self,
        request: ReviewRequest,
        draft: Draft,
        *,
        viewer: Person | None,
        firm_name: str,
        document_title: str,
    ) -> None:
        self.request = request
        self.viewer = viewer
        self.firm_name = firm_name
        self.document_title = document_title
        self.cited: dict[str, CitedFact] = {}
        for statement in request.statements:
            for cited in statement.facts:
                self.cited.setdefault(cited.fact.id, cited)
        self._draft_facts = self.valid_fact_decisions(draft)
        self.fact_states = {fid: self._fact_state(c) for fid, c in self.cited.items()}
        self._draft_answers = self.valid_answers(draft)
        self._draft_assumptions = self.valid_assumptions(draft)
        self.question_states = [self._question_state(q) for q in request.open_questions]

    def valid_fact_decisions(self, draft: Draft) -> dict[str, Decision]:
        """Return the viewer's held decisions that still describe the facts as they now are."""
        return {
            fid: decision
            for fid, decision in draft.facts.items()
            if self._is_the_viewers(decision)
            and fid in self.cited
            and decision.judged_digest == digest_json(self.cited[fid].fact.judged_basis())
        }

    def _is_the_viewers(self, decision: Decision) -> bool:
        return self.viewer is not None and decision.reviewer == self.viewer

    def valid_answers(self, draft: Draft) -> dict[str, Decision]:
        """Return the viewer's held answers to questions that are still on the brief."""
        ids = {q.id for q in self.request.open_questions}
        return {
            qid: d for qid, d in draft.answers.items() if qid in ids and self._is_the_viewers(d)
        }

    def valid_assumptions(self, draft: Draft) -> dict[str, str]:
        """Return the held assumptions for questions that are still on the brief."""
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
            return QuestionState(question, "settled")
        return QuestionState(question, "open")

    @property
    def facts_waiting(self) -> list[CitedFact]:
        """The facts that still need a decision, in the order the brief cites them."""
        return [self.cited[f] for f, s in self.fact_states.items() if not s.settled]

    def next_waiting(self, current_id: str) -> str | None:
        """Return the id of the next fact that needs a decision after ``current_id``.

        The search goes on from the current fact to the end of the brief and then from its start,
        and the current fact is counted as decided.

        Args:
            current_id: The fact the reviewer is on.

        Returns:
            The id, or None when no other fact is waiting.
        """
        ids = list(self.cited)
        start = ids.index(current_id) + 1 if current_id in ids else 0
        for fid in ids[start:] + ids[:start]:
            if fid != current_id and not self.fact_states[fid].settled:
                return fid
        return None

    @property
    def questions_waiting(self) -> list[OpenQuestion]:
        """The open questions that are neither answered nor accepted as assumptions."""
        return [s.question for s in self.question_states if not s.settled]

    @property
    def rejected_facts(self) -> list[CitedFact]:
        """The facts the reviewer has rejected."""
        return [self.cited[f] for f, s in self.fact_states.items() if s.rejected]

    def cannot_sign_because(self) -> str | None:
        """Say in words why the brief cannot be signed yet, or return None when it can."""
        waiting, open_questions = self.facts_waiting, self.questions_waiting
        if waiting or open_questions:
            parts = []
            if waiting:
                parts.append(f"{_plural(len(waiting), 'fact')} without a decision")
            if open_questions:
                parts.append(f"{_plural(len(open_questions), 'question')} not answered or accepted")
            return "The brief cannot be signed yet: " + " and ".join(parts) + "."
        if self.rejected_facts:
            return (
                f"You rejected {_plural(len(self.rejected_facts), 'fact')} that the brief cites. "
                "Return the brief so that it can be written again."
            )
        return None

    def answer(self) -> Answer:
        """Build the page's sentence and tiles from the same counts."""
        statements = len(self.request.statements)
        facts = len(self.cited)
        settled = sum(s.settled for s in self.fact_states.values())
        questions = len(self.question_states)
        questions_settled = sum(s.settled for s in self.question_states)
        waiting_facts, waiting_questions = facts - settled, questions - questions_settled
        head = (
            f"The brief for {self.firm_name} has {_plural(statements, 'statement')} resting on "
            f"{_plural(facts, 'fact')}."
        )
        if waiting_facts or waiting_questions:
            needs = []
            if waiting_facts:
                needs.append(_plural(waiting_facts, "fact"))
            if waiting_questions:
                needs.append(_plural(waiting_questions, "question"))
            sentence = (
                f"{head} {' and '.join(needs)} still need your decision before it can be signed."
            )
            if waiting_facts + waiting_questions == 1:
                sentence = sentence.replace("still need", "still needs")
        elif self.rejected_facts:
            sentence = (
                f"{head} You rejected {_plural(len(self.rejected_facts), 'fact')}, so the brief "
                "can be returned but not signed."
            )
        else:
            sentence = f"{head} Every fact and question is settled, so it is ready for you to sign."
        return Answer(
            sentence=sentence,
            tiles=(
                Tile("Statements", str(statements)),
                Tile(
                    "Facts decided",
                    f"{settled} of {facts}",
                    "needs_person" if waiting_facts else "normal",
                    "Facts you decided or that an earlier review decided and nothing has changed",
                ),
                Tile(
                    "Questions settled",
                    f"{questions_settled} of {questions}",
                    "needs_person" if waiting_questions else "normal",
                    "Questions you answered or accepted as an assumption",
                ),
            ),
        )
