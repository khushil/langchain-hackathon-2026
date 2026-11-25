"""The LangSmith client a page reads a trace's link and totals with."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from fsi_common.evals.upload import DEFAULT_ENDPOINT

CONNECT_MS, READ_MS = 1500, 2000
"""How long the client waits to connect and to read, so a page is never held for long."""


def tracing_is_on(env: Mapping[str, str]) -> bool:
    """Return whether LangSmith tracing is switched on, as LangSmith reads it."""
    return any(
        env.get(name, "").strip().lower() == "true"
        for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")
    )


def traced_client(env: Mapping[str, str] | None = None) -> Any | None:
    """Make the LangSmith client for the workspace the environment names.

    Args:
        env: The environment; the process's when omitted.

    Returns:
        The client; None when tracing is off or no key is set, so nothing is asked of LangSmith.
    """
    env = os.environ if env is None else env
    key = env.get("LANGSMITH_API_KEY") or env.get("LANGSMITH_KEY")
    if not tracing_is_on(env) or not key:
        return None
    from langsmith import Client

    return Client(
        api_key=key,
        api_url=env.get("LANGSMITH_ENDPOINT", DEFAULT_ENDPOINT),
        timeout_ms=(CONNECT_MS, READ_MS),
    )
