"""The chat model every agent in the product runs on: headless Claude Code, isolated and capped."""

from fsi_common.model.chat_model import (
    CallRecord,
    ChatClaudeHeadless,
    call_records,
    make_chat_model,
    reset_call_records,
)
from fsi_common.model.errors import (
    HeadlessCallError,
    HeadlessTimeoutError,
    IsolationError,
    MalformedResponseError,
    ModelConfigError,
    ModelError,
    RecordingShapeError,
    ReplayMissError,
)
from fsi_common.model.gate import PROCESS_CAP, process_gate

__all__ = [
    "PROCESS_CAP",
    "CallRecord",
    "ChatClaudeHeadless",
    "HeadlessCallError",
    "HeadlessTimeoutError",
    "IsolationError",
    "MalformedResponseError",
    "ModelConfigError",
    "ModelError",
    "RecordingShapeError",
    "ReplayMissError",
    "call_records",
    "make_chat_model",
    "process_gate",
    "reset_call_records",
]
