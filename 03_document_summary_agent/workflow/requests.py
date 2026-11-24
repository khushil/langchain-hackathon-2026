"""Read a run's request: the document, the firm, and the optional section filter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from context.reader import DocumentRead, SectionRead

from workflow.errors import InvalidRequestError, UnknownSectionError


def request_of(state: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the run's request from its state.

    Args:
        state: The graph state.

    Returns:
        The ``BriefRequest`` with its optional ``sections`` key.
    """
    return state["request"]


def selected_sections(document: DocumentRead, request: Mapping[str, Any]) -> list[SectionRead]:
    """Return the sections a run reads: those the request names, or every section.

    Args:
        document: The document read.
        request: The run's request; its ``sections`` key, when present, lists section numbers.

    Returns:
        The sections in document order, each once.

    Raises:
        InvalidRequestError: If the request holds an empty ``sections`` list; leave the key out to
            read every section.
        UnknownSectionError: If the request names a section the document does not have; every
            such number is named.
    """
    wanted = request.get("sections")
    if wanted is None:
        return list(document.sections)
    if not wanted:
        raise InvalidRequestError(
            "The request holds an empty list of sections; leave 'sections' out to read them all."
        )
    known = {section.number for section in document.sections}
    unknown = sorted({str(n) for n in wanted} - known)
    if unknown:
        raise UnknownSectionError(
            f"The request names section(s) {', '.join(unknown)}, which {document.source.key} "
            f"does not have; its sections are {', '.join(s.number for s in document.sections)}."
        )
    chosen = {str(n) for n in wanted}
    return [section for section in document.sections if section.number in chosen]
