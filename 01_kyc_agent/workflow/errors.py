"""The errors of the workflow, each naming the item that stopped the run."""

from __future__ import annotations


class WorkflowError(Exception):
    """Base class of every error the workflow raises."""


class ReadCallError(WorkflowError):
    """An application's model call returned something that is not a reading of it."""


class BriefDraftError(WorkflowError):
    """The statements written for the reviewer cannot be built into a brief record."""


class StoredDecisionError(WorkflowError):
    """A decision in the store is not a valid decision, and is never skipped."""


class InvalidRequestError(WorkflowError):
    """The request lacks a field a run needs."""


class UnitNotHeldError(WorkflowError):
    """A fact cites an application or screening that the run's state does not hold as a unit."""


class UnknownSubjectError(WorkflowError):
    """A decision is on something the run does not hold, so no customer can be named for it."""
