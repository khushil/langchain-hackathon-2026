"""The interfaces the three lanes build to: the engine's steps, the judge, the pages, the measures.

Each is a Protocol, so a lane builds against a fake of another lane's part. Signatures here are
fixed by the contract; a change is the lead's ruling.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from assessment.records import (
    Bundle,
    Candidate,
    FirmProfile,
    JudgementAnswer,
    JudgementRequest,
    Register,
)
from assessment.texts import TextIndex
from fsi_common.records import Fact

JUDGE_ROLE = "assess"
"""The ``get_model`` role of the one call per applicable obligation (to be added to
``utils/models.py`` by the engine lane)."""

PROMPT_VERSION = "assess.v1"
"""The judgement prompt's version, carried in every request and so in every replay key."""


class RegisterBuilder(Protocol):
    """Builds the register from the texts and the profile, by code only."""

    def __call__(self, texts: TextIndex, profile: FirmProfile) -> Register:
        """Return the register."""
        ...


class GraphBuilder(Protocol):
    """Finds the document graph's facts by code, each with a quote at both ends."""

    def __call__(self, texts: TextIndex) -> list[Fact]:
        """Return the graph facts."""
        ...


class CandidateFinder(Protocol):
    """Finds every candidate clause of the documents for each applicable obligation, by code."""

    def __call__(
        self, register: Register, texts: TextIndex, graph: Sequence[Fact], *, second_look: bool
    ) -> list[Candidate]:
        """Return every candidate, kept and dropped; ``second_look`` widens the search."""
        ...


class Judge(Protocol):
    """Makes the one model call for one obligation, through ``get_model(JUDGE_ROLE)``."""

    def __call__(self, request: JudgementRequest) -> JudgementAnswer:
        """Return the answer, before any plain-code check."""
        ...


class Engine(Protocol):
    """Runs the whole assessment of one corpus and returns the bundle, checked."""

    def __call__(self, corpus: str, *, judge: Judge) -> Bundle:
        """Return the bundle; ``require_valid`` has passed on it."""
        ...


class BundleSource(Protocol):
    """What the pages and the measures read a bundle through."""

    def __call__(self, corpus: str) -> Path:
        """Return the folder of the latest bundle of a corpus (``read_bundle`` reads it)."""
        ...
