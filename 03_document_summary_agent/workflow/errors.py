"""The errors of the workflow, each naming the item that stopped the run."""

from __future__ import annotations


class WorkflowError(Exception):
    """Base class of every error the workflow raises."""


class UnknownSectionError(WorkflowError):
    """The request asks for a section the document does not have."""


class SectionCallError(WorkflowError):
    """A section's model call returned something that is not a section summary."""


class BriefDraftError(WorkflowError):
    """The brief the model wrote cannot be built into a brief record."""


class BriefCitationError(WorkflowError):
    """A statement of the brief cites a fact that is missing or failed a check.

    Attributes:
        fact_ids: The ids of the facts that cannot be cited.
    """

    def __init__(self, message: str, *, fact_ids: list[str]) -> None:
        super().__init__(message)
        self.fact_ids = fact_ids


class StoredDecisionError(WorkflowError):
    """A decision in the store is not a valid decision, and is never skipped."""


class InvalidRequestError(WorkflowError):
    """The request lacks a field a run needs."""


class UnitNotHeldError(WorkflowError):
    """A fact cites a paragraph or row that the run's state does not hold as a unit."""
