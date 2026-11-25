"""The engine's graph state: the contract's state and the task one application's read is given."""

from __future__ import annotations

from typing import Any, TypedDict

from utils.kyc_state import KycState


class EngineState(KycState, total=False):
    """The graph state; it holds the fields ``KycState`` names and no more."""


class ReadTask(TypedDict):
    """What one fanned-out application read is given."""

    request: dict[str, Any]
    customer_id: str
