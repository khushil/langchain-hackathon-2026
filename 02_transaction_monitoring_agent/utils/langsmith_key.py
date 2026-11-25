"""Whether a step that talks to LangSmith may run: the reader has set a key and tracing on."""

import os
from collections.abc import Mapping

from utils.models import tracing_enabled

NEEDS_KEY = (
    "This step needs LangSmith: set LANGSMITH_API_KEY and LANGSMITH_TRACING=true in the .env in "
    "the repository root, then run it again."
)
"""The one sentence a notebook cell prints in place of a step that needs LangSmith."""


def langsmith_ready(env: Mapping[str, str] | None = None) -> bool:
    """Say whether a step that writes to LangSmith may run.

    Args:
        env: The environment; the process's own when absent.

    Returns:
        True only when tracing is on and a key is set, so a notebook never writes to LangSmith
        unless the reader asked it to.
    """
    env = os.environ if env is None else env
    has_key = any(env.get(name, "").strip() for name in ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"))
    return tracing_enabled(env) and has_key


__all__ = ["NEEDS_KEY", "langsmith_ready"]
