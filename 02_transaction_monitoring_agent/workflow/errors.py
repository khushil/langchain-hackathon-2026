"""The errors of the workflow, each naming the item that stopped the run."""

from __future__ import annotations


class WorkflowError(Exception):
    """Base class of every error the workflow raises."""


class InvalidRequestError(WorkflowError):
    """The request lacks a field a run needs."""


class AssessorPausedError(WorkflowError):
    """The assessor's tool asked a person, which only the review step may do."""


class NothingToReviewError(WorkflowError):
    """No transaction has an assessment that passed its checks, so there is no brief to write."""


class StoredDecisionError(WorkflowError):
    """A decision in the store is not a valid decision, and is never skipped."""


class UnitNotHeldError(WorkflowError):
    """A fact cites a transaction or a profile that the run's state does not hold as a unit."""
