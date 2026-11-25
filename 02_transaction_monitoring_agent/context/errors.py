"""The errors of the context layer, each saying in words what could not be read or closed."""

from __future__ import annotations


class ContextError(Exception):
    """Base class of every error the context layer raises."""


class CustomerNotFoundError(ContextError):
    """The customer is not in the profile table."""


class EmptyStreamError(ContextError):
    """The customer has no transaction in the window asked for."""


class AssessmentReadError(ContextError):
    """A recorded assessment cannot become a fact, and nothing is dropped to hide it."""


class AccountingError(ContextError):
    """The units read and the units accounted for do not close.

    Attributes:
        missing: Anchors of units that were read and are not in the state.
        unexpected: Anchors of units in the state that the source was never read into.
    """

    def __init__(
        self, message: str, *, missing: list[str] | None = None, unexpected: list[str] | None = None
    ) -> None:
        super().__init__(message)
        self.missing = missing or []
        self.unexpected = unexpected or []
