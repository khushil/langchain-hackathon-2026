"""Whether an earlier decision carries over to the record now on the table, asks again, or none.

On a rerun a person should be asked only about what changed. A decision carries when its subject
has the same id and the same judged digest (the model, the prompt, the extractor or a check's
wording may have moved); it asks again, with the difference named, when the id is the same and
what the person judged is not; and a record with no decision on its id is asked fresh.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

from fsi_common.ids import digest_json
from fsi_common.records.base import Addressed, NonBlank, Part
from fsi_common.records.decisions import Decision

CarryOutcome = Literal["carried", "ask_again", "fresh"]
"""carried: shown as decided, with the earlier date and reviewer; ask_again: put to the person
with the earlier decision and the difference; fresh: put to the person with no earlier decision."""


class CarryOver(Part):
    """What becomes of an earlier decision on a rerun, with the difference when it asks again."""

    outcome: CarryOutcome = Field(description="Carried, ask again, or fresh")
    decision: Decision | None = Field(
        description="The earlier decision; none when the record is asked fresh"
    )
    differences: list[NonBlank] = Field(
        description="For ask again: each judged field that changed, for example 'quote', "
        "'attributes.deadline' or 'checks.deadline-verbatim.v1'"
    )

    @model_validator(mode="after")
    def _outcome_fits(self) -> Self:
        if (self.outcome == "fresh") != (self.decision is None):
            raise PydanticCustomError(
                "carry.outcome", "a record asked fresh has no earlier decision, and only it"
            )
        if (self.outcome == "ask_again") != bool(self.differences):
            raise PydanticCustomError(
                "carry.outcome", "a record asked again names what changed, and only it does"
            )
        return self


def judged_differences(before: Any, after: Any, *, path: str = "") -> list[str]:
    """Name each judged field that differs between two judged bases.

    Maps are compared key by key, and a list of check results check by check, so the names say
    which attribute or which check moved.

    Args:
        before: The judged basis a decision recorded.
        after: The judged basis of the record now.
        path: The name of the field being compared, for the nested calls.

    Returns:
        The names of the fields that differ, sorted; empty when the two are equal.
    """
    if isinstance(before, dict) and isinstance(after, dict):
        names: list[str] = []
        for key in sorted(set(before) | set(after)):
            inner = f"{path}.{key}" if path else key
            if key not in before or key not in after:
                names.append(inner)
            else:
                names += judged_differences(before[key], after[key], path=inner)
        return sorted(names)
    if _check_list(before) and _check_list(after):
        old = {(c["check"], c["outcome"]) for c in before}
        new = {(c["check"], c["outcome"]) for c in after}
        return sorted({f"{path}.{check}" for check, _ in old ^ new})
    return [] if before == after else [path or "record"]


def _check_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, dict) and set(item) == {"check", "outcome"} for item in value
    )


def carry_over(earlier: Decision | None, current: Addressed) -> CarryOver:
    """Say what becomes of an earlier decision now that ``current`` is on the table.

    Args:
        earlier: The latest decision a person made on this record's id, or None if there is none.
            A decision on another id is no decision on this record.
        current: The record as this run produced it.

    Returns:
        ``carried`` with the decision when the judged digest is the same; ``ask_again`` with the
        decision and the changed fields when it is not; ``fresh`` when there is no decision.
    """
    if earlier is None or earlier.subject_id != current.id:
        return CarryOver(outcome="fresh", decision=None, differences=[])
    now = current.judged_basis()
    if earlier.judged_digest == digest_json(now):
        return CarryOver(outcome="carried", decision=earlier, differences=[])
    differences = judged_differences(earlier.judged, now) or ["record"]
    return CarryOver(outcome="ask_again", decision=earlier, differences=differences)
