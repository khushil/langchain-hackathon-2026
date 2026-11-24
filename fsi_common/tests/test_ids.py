"""Tests of the canonical JSON form, the digests and the content-derived ids."""

import math

import pytest

from fsi_common.ids import canonical_json, content_id, digest_bytes, digest_json, digest_text


def test_canonical_json_sorts_keys_and_drops_spaces():
    assert canonical_json({"b": 1, "a": [True, None]}) == '{"a":[true,null],"b":1}'


def test_canonical_json_keeps_non_ascii_text_as_utf8():
    assert canonical_json({"total_assets": "£9 billion"}) == '{"total_assets":"£9 billion"}'


def test_canonical_json_refuses_nan():
    with pytest.raises(ValueError, match="Out of range float values"):
        canonical_json({"x": math.nan})


def test_digest_bytes_is_prefixed_sha256():
    assert digest_bytes(b"") == (
        "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_digest_text_does_not_normalise_white_space():
    assert digest_text("a b") != digest_text("a  b")


def test_digest_json_ignores_key_order():
    assert digest_json({"a": 1, "b": 2}) == digest_json({"b": 2, "a": 1})


def test_content_id_has_prefix_and_16_hex_characters():
    value = content_id("fact", {"quote": "Firms must"})
    prefix, hex_part = value.split(":")
    assert prefix == "fact"
    assert len(hex_part) == 16
    assert int(hex_part, 16) >= 0


def test_content_id_is_the_same_for_the_same_content():
    assert content_id("fact", {"a": 1, "b": 2}) == content_id("fact", {"b": 2, "a": 1})


def test_content_id_differs_when_the_content_differs():
    assert content_id("fact", {"a": 1}) != content_id("fact", {"a": 2})
