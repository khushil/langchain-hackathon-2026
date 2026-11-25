"""The engine's graph state: the contract's state and the raw section summaries."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from utils.records import PARAGRAPH_SCHEME
from utils.state import BriefState, RecordJson, merge_records, merge_sections


def merge_paragraph_reads(
    left: dict[str, Any] | None, right: dict[str, Any] | None
) -> dict[str, Any]:
    """Merge second reads written in parallel, one writer per paragraph, in paragraph order.

    Args:
        left: The second reads so far, by paragraph anchor such as ``para:9.3``.
        right: One or more sections' new second reads.

    Returns:
        Every second read, ordered by the numbers of the paragraph (2.4 before 10.1).

    Raises:
        ConflictingWriteError: If one paragraph arrives with two different records.
    """
    merged = merge_records(left, right)
    prefix = f"{PARAGRAPH_SCHEME}:"

    def order(key: str) -> tuple[int | str, ...]:
        return tuple(int(p) if p.isdigit() else p for p in key.removeprefix(prefix).split("."))

    return dict(sorted(merged.items(), key=lambda item: order(item[0])))


class EngineState(BriefState, total=False):
    """The contract's ``BriefState`` and two more fields, ``raw_summaries`` and ``second_reads``.

    ``raw_summaries`` holds, by section number, the ``SectionSummary`` JSON each section's model
    call returned, untouched, so a score of the sub-agent reads what the model said and not what
    the records made of it. It is the section's first read only.

    ``second_reads`` holds, by paragraph anchor (``para:9.3``), each second read of a paragraph
    that held an obligation marker and no obligation fact: its section, the marker, the task
    asked, the summary the model returned untouched, whether an obligation fact that passed its
    checks was read from the paragraph (``gave_obligation``), the ids of the obligation facts on
    it, and the id of the open question that asks about the paragraph.
    """

    raw_summaries: Annotated[dict[str, RecordJson], merge_sections]
    second_reads: Annotated[dict[str, RecordJson], merge_paragraph_reads]


class SectionTask(TypedDict):
    """What one fanned-out section step is given."""

    request: dict[str, Any]
    section: str
