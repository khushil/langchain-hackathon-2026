"""Tests for the request hash and the store of recorded calls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fsi_common.model.errors import ReplayMissError
from fsi_common.model.recording import (
    Recording,
    RecordingStore,
    canonical_request,
    mint_tool_call_id,
    request_hash,
)

TURNS = [{"role": "user", "content": "Hello"}]


def _request(**overrides: object) -> dict:
    base: dict = {
        "model": "sonnet",
        "effort": "low",
        "system": "Be brief.",
        "messages": TURNS,
        "schema": None,
    }
    base.update(overrides)
    return canonical_request(**base)


def test_hash_is_stable_and_sixty_four_hex_digits() -> None:
    first = request_hash(_request())
    assert first == request_hash(_request())
    assert len(first) == 64
    assert int(first, 16) >= 0


@pytest.mark.parametrize(
    "change",
    [
        {"model": "opus"},
        {"effort": "high"},
        {"effort": None},
        {"system": "Be thorough."},
        {"messages": [{"role": "user", "content": "Hello!"}]},
        {"schema": {"type": "object"}},
    ],
)
def test_every_part_of_the_request_changes_the_hash(change: dict) -> None:
    assert request_hash(_request(**change)) != request_hash(_request())


def test_key_order_does_not_change_the_hash() -> None:
    one = _request(schema={"a": 1, "b": {"c": 2, "d": 3}})
    two = _request(schema={"b": {"d": 3, "c": 2}, "a": 1})
    assert request_hash(one) == request_hash(two)


def test_tool_call_ids_are_deterministic_and_distinct() -> None:
    key = request_hash(_request())
    first = mint_tool_call_id(key, 0, "task", {"description": "s1"})
    assert first == mint_tool_call_id(key, 0, "task", {"description": "s1"})
    assert first.startswith("call_")
    assert len(first) == len("call_") + 24
    others = {
        mint_tool_call_id(key, 1, "task", {"description": "s1"}),
        mint_tool_call_id(key, 0, "task", {"description": "s2"}),
        mint_tool_call_id(key, 0, "other", {"description": "s1"}),
        mint_tool_call_id("0" * 64, 0, "task", {"description": "s1"}),
    }
    assert first not in others
    assert len(others) == 4


def _recording(key: str) -> Recording:
    return Recording(
        key=key,
        request=_request(),
        response={"content": "Hi", "tool_calls": [], "usage": {"output_tokens": 1}},
        meta={"recorded_at": "2026-11-24T18:00:00Z", "duration_s": 1.5},
    )


def test_store_round_trips_a_recording(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path / "rec")
    key = request_hash(_request())
    store.save(_recording(key))
    loaded = store.load(key)
    assert loaded == _recording(key)
    on_disk = json.loads((tmp_path / "rec" / f"{key}.json").read_text(encoding="utf-8"))
    assert on_disk["key"] == key
    assert list((tmp_path / "rec").iterdir()) == [tmp_path / "rec" / f"{key}.json"]


def test_a_miss_names_the_hash(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    key = request_hash(_request())
    with pytest.raises(ReplayMissError, match=key) as caught:
        store.load(key)
    assert caught.value.request_hash == key


def test_a_recording_filed_under_the_wrong_hash_is_refused(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    key = request_hash(_request())
    store.save(_recording(key))
    other = request_hash(_request(model="opus"))
    (tmp_path / f"{key}.json").rename(tmp_path / f"{other}.json")
    with pytest.raises(ReplayMissError, match="holds a different request"):
        store.load(other)


def test_a_malformed_key_is_refused(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    with pytest.raises(ValueError, match="not a SHA-256 hex digest"):
        store.load("../../etc/passwd")
