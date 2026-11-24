"""The errors of the context layer, each saying in words what could not be read or closed."""

from __future__ import annotations


class ContextError(Exception):
    """Base class of every error the context layer raises."""


class DocumentNotFoundError(ContextError):
    """The document is not in the library."""


class DocumentFormatError(ContextError):
    """A section holds a block that is not a numbered paragraph of that section."""


class FirmNotFoundError(ContextError):
    """The firm is not in the firm table."""


class SectionReadError(ContextError):
    """A section's result cannot become cited facts, and nothing is dropped to hide it."""


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
