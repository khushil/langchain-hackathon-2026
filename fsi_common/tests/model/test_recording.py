"""Tests for the request hash and the store of recorded calls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fsi_common.model.errors import RecordingShapeError, ReplayMissError
from fsi_common.model.recording import (
    RECORDING_SHAPE,
    Recording,
    RecordingStore,
    canonical_request,
    mint_tool_call_id,
    recording_problems,
    request_hash,
)

REPOSITORY = Path(__file__).resolve().parents[3]

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
        request_sha256=key,
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
    assert on_disk["request_sha256"] == key
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


@pytest.mark.parametrize(
    ("where", "extra", "named"),
    [
        ("meta", {"rate_limit": {"utilization": 0.46}}, "meta.rate_limit"),
        ("response", {"total_cost_usd": 0.02}, "response.total_cost_usd"),
        ("usage", {"service_tier": "standard"}, "response.usage.service_tier"),
        ("meta", {"num_turns": 2}, "meta.num_turns"),
        ("top", {"account": "x"}, "account"),
    ],
)
def test_a_recording_holding_a_key_outside_the_allow_list_is_refused(
    tmp_path: Path, where: str, extra: dict, named: str
) -> None:
    store = RecordingStore(tmp_path)
    key = request_hash(_request())
    store.save(_recording(key))
    path = tmp_path / f"{key}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    target = {"top": data, "meta": data["meta"], "response": data["response"]}.get(where)
    if where == "usage":
        target = data["response"]["usage"]
    target.update(extra)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RecordingShapeError, match=named.replace(".", r"\.")) as caught:
        store.load(key)
    assert caught.value.keys == [named]


def test_the_store_never_writes_a_key_outside_the_allow_list(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    key = request_hash(_request())
    leaky = Recording(
        request_sha256=key,
        request=_request(),
        response={"content": "Hi", "tool_calls": [], "total_cost_usd": 0.01},
        meta={"recorded_at": "2026-11-24T18:00:00Z", "duration_s": 1.5, "rate_limit": {}},
    )
    with pytest.raises(RecordingShapeError) as caught:
        store.save(leaky)
    assert caught.value.keys == ["meta.rate_limit", "response.total_cost_usd"]
    assert not list(tmp_path.iterdir())


def test_every_committed_recording_holds_only_allowed_keys() -> None:
    files = sorted(REPOSITORY.glob("*/recordings/*.json"))
    assert files, "no committed recordings found"
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert recording_problems(data) == [], path.name
        assert request_hash(data["request"]) == data["request_sha256"] == path.stem


def _set_cost_in_tool_call(data: dict) -> None:
    data["response"]["tool_calls"] = [{"name": "t", "args": {}, "total_cost_usd": 0.02}]


def _set_dict_in_plugins(data: dict) -> None:
    data["meta"]["init"] = {"plugins": [{"rate_limit": {"status": "allowed"}}]}


def _set_usage_as_list(data: dict) -> None:
    data["response"]["usage"] = [{"service_tier": "standard"}]


def _set_init_as_list(data: dict) -> None:
    data["meta"]["init"] = [{"rate_limit": {}}]


def _set_tool_calls_as_object(data: dict) -> None:
    data["response"]["tool_calls"] = {"name": "t", "args": {}}


def _set_dict_as_token_count(data: dict) -> None:
    data["response"]["usage"] = {"input_tokens": {"utilization": 0.46}}


@pytest.mark.parametrize(
    ("plant", "named"),
    [
        (_set_cost_in_tool_call, "response.tool_calls[0].total_cost_usd"),
        (_set_dict_in_plugins, "meta.init.plugins[0] (expected str)"),
        (_set_usage_as_list, "response.usage (expected an object)"),
        (_set_init_as_list, "meta.init (expected an object)"),
        (_set_dict_as_token_count, "response.usage.input_tokens (expected int)"),
        (_set_tool_calls_as_object, "response.tool_calls (expected a list)"),
    ],
)
def test_a_field_hidden_in_a_list_or_another_shape_is_refused(
    tmp_path: Path, plant, named: str
) -> None:
    store = RecordingStore(tmp_path)
    key = request_hash(_request())
    store.save(_recording(key))
    path = tmp_path / f"{key}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    plant(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RecordingShapeError) as caught:
        store.load(key)
    assert caught.value.keys == [named]


def test_the_shape_is_plain_json_for_a_copy_outside_the_product() -> None:
    assert json.loads(json.dumps(RECORDING_SHAPE)) == RECORDING_SHAPE
