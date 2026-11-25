"""The template function that gives a review's page its trace link and totals."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from jinja2 import pass_context
from jinja2.runtime import Context

from fsi_common.tracing.lookup import TraceLookup, TraceView


class RootRun(Protocol):
    """Where a review's first graph run was traced."""

    run_id: str | None
    project_id: str | None
    started_at: str | None


def trace_view_global(
    lookup: TraceLookup, root_of: Callable[[str], RootRun | None]
) -> Callable[..., TraceView | None]:
    """Make the function a page calls to learn the trace of the review it shows.

    The review is the one in the page's address (``/runs/{thread}/...``), so a template needs no
    argument and a route needs no change.

    Args:
        lookup: Reads the link and totals from LangSmith.
        root_of: Gives where a review's first graph run was traced, or None for an unknown review.

    Returns:
        A template function that takes no argument and gives the trace's link and totals, or None
        for a page that is not about one review, an untraced run or an unreachable LangSmith.
    """

    @pass_context
    def trace_view(context: Context) -> TraceView | None:
        request: Any = context.get("request")
        params = getattr(request, "path_params", None) or {}
        thread_id = params.get("thread")
        if not thread_id:
            return None
        root = root_of(thread_id)
        if root is None:
            return None
        return lookup.view(
            thread_id=thread_id,
            run_id=root.run_id,
            project_id=root.project_id,
            started_at=root.started_at,
        )

    return trace_view
