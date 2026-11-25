"""Shared fixtures of the assessment contract's tests: the real texts, read once, offline."""

from __future__ import annotations

import pytest
from assessment.texts import TextIndex, load_texts


def _no_network(address: str, headers: object) -> bytes:
    raise OSError(f"the contract's tests make no network call ({address})")


@pytest.fixture(scope="session")
def texts() -> TextIndex:
    """The three regulations and the Harbour Mutual Bank set, read whole without a fetch."""
    return load_texts("harbour-mutual-bank", opener=_no_network)
