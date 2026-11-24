"""Named errors raised by the chat model over headless Claude Code."""

from __future__ import annotations

STDERR_HEAD_CHARS = 2000


class ModelError(Exception):
    """Base class for every error the model adapter raises."""


class ModelConfigError(ModelError):
    """The adapter was configured or called with a value it cannot honour."""


class HeadlessCallError(ModelError):
    """A headless call failed: a non-zero exit, or a result the command flagged as an error."""

    def __init__(self, message: str, *, exit_code: int | None, stderr: str = "") -> None:
        """Build the error.

        Args:
            message: What went wrong, in plain words.
            exit_code: The process's exit code, or None when it never exited.
            stderr: The process's standard error; only its first part is kept.
        """
        self.exit_code = exit_code
        self.stderr_head = stderr[:STDERR_HEAD_CHARS]
        detail = f" Standard error begins: {self.stderr_head.strip()!r}" if self.stderr_head else ""
        super().__init__(f"{message}{detail}")


class HeadlessTimeoutError(HeadlessCallError):
    """A headless call did not finish within its timeout and was stopped."""


class MalformedResponseError(ModelError):
    """A headless call finished but its output was not in the shape the adapter expects."""


class IsolationError(ModelError):
    """A headless call started with a customisation loaded that isolation forbids."""


class ReplayMissError(ModelError):
    """No recording exists for a request, so replay cannot answer it."""

    def __init__(self, request_hash: str, *, reason: str = "no recording") -> None:
        """Build the error.

        Args:
            request_hash: The SHA-256 of the request's canonical form.
            reason: Why the recording could not be served.
        """
        self.request_hash = request_hash
        super().__init__(
            f"Replay has {reason} for request {request_hash}. Record it with a live call "
            "in mode 'record' first; replay never invents an answer."
        )


class RecordingShapeError(ModelError):
    """A recording departs from the allow-list, so it is neither written nor read."""

    def __init__(self, name: str, keys: list[str]) -> None:
        """Build the error.

        Args:
            name: The recording's file name or request hash.
            keys: The path of every field outside the allow-list or in another shape.
        """
        self.keys = keys
        super().__init__(
            f"The recording {name} holds fields a recording never keeps, or keeps in another "
            f"shape: {', '.join(keys)}. "
            "A recording keeps the request, the reply's content, tool calls, reported model and "
            "token counts, and the run's start evidence, time and duration; nothing else."
        )
