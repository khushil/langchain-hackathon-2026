"""The errors of the regulation readers, each saying in words what could not be fetched or read."""

from __future__ import annotations

from context.errors import ContextError


class RegulationError(ContextError):
    """Base class of every error the regulation readers raise."""


class RegulationFetchError(RegulationError):
    """A regulation could not be fetched from its publisher."""


class DigestMismatchError(RegulationError):
    """The bytes fetched or cached are not the bytes whose digest the manifest records."""


class RegulationFormatError(RegulationError):
    """A regulation's text does not read into units whose numbering and counts close."""


class RegulationToolMissingError(RegulationError):
    """A program the PDF reader needs is not installed."""


class RegulationAccountingError(RegulationError):
    """The units read do not match the units the pinned record says the regulation holds."""

    def __init__(
        self,
        message: str,
        *,
        missing: list[str] | None = None,
        unexpected: list[str] | None = None,
        changed: list[str] | None = None,
        repeated: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.missing = missing or []
        self.unexpected = unexpected or []
        self.changed = changed or []
        self.repeated = repeated or []
