"""The graph's state: records as JSON, merged by reducers that give the same state in any order.

State values are records as JSON (``record.to_json()``), validated with ``fsi_common`` at each
node's boundary, because LangGraph's checkpointer stores JSON safely and refuses unregistered
Python types in a future version. Collections are dicts keyed by id, merged by reducers that sort
their keys.
"""

from __future__ import annotations

from typing import Annotated, Any, NotRequired, TypedDict

RecordJson = dict[str, Any]
"""A record as JSON, as ``fsi_common`` writes it."""


class ConflictingWriteError(Exception):
    """Two writers gave different content under one key, which content-derived ids rule out."""


def merge_records(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Merge two writes of records keyed by id; the same id must carry the same content.

    Args:
        left: The state's records so far.
        right: A node's new records.

    Returns:
        Every record, keys sorted.

    Raises:
        ConflictingWriteError: If one id arrives with two different contents.
    """
    merged = dict(left or {})
    for key, value in (right or {}).items():
        if key in merged and merged[key] != value:
            raise ConflictingWriteError(f"Two different records were written under {key}.")
        merged[key] = value
    return dict(sorted(merged.items()))


def update_records(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Merge two writes of records whose state may move on, such as an open question being answered.

    Args:
        left: The state's records so far.
        right: A node's new or updated records; an update replaces the earlier copy.

    Returns:
        Every record, keys sorted.
    """
    return dict(sorted({**(left or {}), **(right or {})}.items()))


class MonitorRequest(TypedDict):
    """What the user asked for: one customer's stream, and optionally a window of it."""

    user_id: str
    request: str
    start: NotRequired[str]
    end: NotRequired[str]


class MonitorInput(TypedDict):
    """The graph's input."""

    request: MonitorRequest


class RunCheck(TypedDict):
    """The result of one plain-code check on the run, such as the unit counts closing."""

    check: str
    subject_id: str
    outcome: str
    detail: str


class MonitorState(MonitorInput, total=False):
    """The shared state of one run, from the request to the sign-off."""

    sources: Annotated[dict[str, RecordJson], merge_records]
    """``source.v1`` records by id: the transactions and the customer profiles."""
    units: Annotated[dict[str, RecordJson], merge_records]
    """``source_unit.v1`` records by id: every transaction of the window and the profile row."""
    unit_text: Annotated[dict[str, str], merge_records]
    """Each unit's line of its data file by unit id; the unit's digest is of this text."""
    raw_assessments: Annotated[dict[str, RecordJson], merge_records]
    """For each transaction of the window, what the starter's agent recorded for it, untouched
    (``audit``, or none when it recorded nothing) and its closing sentence (``reply``)."""
    facts: Annotated[dict[str, RecordJson], merge_records]
    """``fact.v1`` records by id."""
    check_results: Annotated[dict[str, RunCheck], merge_records]
    """Run-level checks by ``<check>|<subject id>``."""
    accounting: Annotated[dict[str, RecordJson], merge_records]
    """``unit_accounting.v1`` records by source id."""
    open_questions: Annotated[dict[str, RecordJson], update_records]
    """``open_question.v1`` records by id; a decision moves a question's state."""
    draft_brief: RecordJson | None
    """The ``brief.v1`` record put to the reviewer."""
    decisions: Annotated[dict[str, RecordJson], merge_records]
    """Decision records by id, this run's and earlier runs' from the store."""
    sign_off: RecordJson | None
    """The sign-off record, once the reviewer has signed or returned the brief."""
