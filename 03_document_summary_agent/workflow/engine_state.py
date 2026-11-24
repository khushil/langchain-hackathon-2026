"""The engine's graph state: the contract's state and the raw section summaries."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from utils.state import BriefState, RecordJson, merge_sections


class EngineState(BriefState, total=False):
    """The contract's ``BriefState`` and one more field, ``raw_summaries``.

    ``raw_summaries`` holds, by section number, the ``SectionSummary`` JSON each section's model
    call returned, untouched, so a score of the sub-agent reads what the model said and not what
    the records made of it.
    """

    raw_summaries: Annotated[dict[str, RecordJson], merge_sections]


class SectionTask(TypedDict):
    """What one fanned-out section step is given."""

    request: dict[str, Any]
    section: str
