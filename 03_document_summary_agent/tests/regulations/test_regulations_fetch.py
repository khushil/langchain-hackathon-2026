"""A regulation is fetched from its publisher, checked against its recorded digest, and cached."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from context.regulations.errors import (
    DigestMismatchError,
    RegulationFetchError,
    RegulationToolMissingError,
)
from context.regulations.fetch import (
    OVERALL_CAP_SECONDS,
    TIMEOUT_SECONDS,
    ensure_regulation,
    fetch_bytes,
    require_tools,
    resolve_cache_dir,
    verify_live,
)
from context.regulations.manifest import (
    CACHE_DIR,
    REGULATIONS_DIR,
    RegulationEntry,
    load_manifest,
)
from fsi_common.ids import digest_bytes

BODY = b"<html>sample act</html>"


def entry(*, digest: str | None = None) -> RegulationEntry:
    return RegulationEntry(
        key="SAMPLE",
        title="Sample Regulation",
        short_name="the sample",
        publisher="Sample publisher",
        address="https://example.org/sample",
        request_headers={"Accept": "application/xhtml+xml"},
        reader="official_journal",
        fetched="2026-11-25",
        digest=digest or digest_bytes(BODY),
        size=len(BODY),
        cache_file="sample.xhtml",
        terms="Fetched at build time and not republished.",
    )


def test_a_fetch_that_matches_its_digest_is_cached_and_returned(tmp_path: Path):
    calls: list[str] = []

    def opener(address: str, headers) -> bytes:
        calls.append(address)
        return BODY

    got = ensure_regulation(entry(), cache_dir=tmp_path, opener=opener)
    assert got == BODY
    assert (tmp_path / "sample.xhtml").read_bytes() == BODY
    assert calls == ["https://example.org/sample"]


def test_a_cached_file_is_used_without_a_second_fetch(tmp_path: Path):
    (tmp_path / "sample.xhtml").write_bytes(BODY)

    def opener(address: str, headers) -> bytes:
        raise AssertionError("the network must not be used when the cache holds the bytes")

    assert ensure_regulation(entry(), cache_dir=tmp_path, opener=opener) == BODY


def test_changed_bytes_at_the_publisher_are_refused_and_not_cached(tmp_path: Path):
    def opener(address: str, headers) -> bytes:
        return BODY + b" changed"

    with pytest.raises(
        DigestMismatchError, match=r"SAMPLE.*sha256:[0-9a-f]{64}.*sha256:[0-9a-f]{64}"
    ):
        ensure_regulation(entry(), cache_dir=tmp_path, opener=opener)
    assert not (tmp_path / "sample.xhtml").exists()


def test_a_cached_file_that_no_longer_matches_is_refused_and_the_publisher_is_asked_again(
    tmp_path: Path,
):
    (tmp_path / "sample.xhtml").write_bytes(BODY + b" edited")
    calls: list[str] = []

    def opener(address: str, headers) -> bytes:
        calls.append(address)
        return BODY

    assert ensure_regulation(entry(), cache_dir=tmp_path, opener=opener) == BODY
    assert calls == ["https://example.org/sample"]
    assert (tmp_path / "sample.xhtml").read_bytes() == BODY


def test_a_wrong_cache_and_wrong_bytes_at_the_publisher_is_a_digest_mismatch(tmp_path: Path):
    (tmp_path / "sample.xhtml").write_bytes(BODY + b" edited")
    with pytest.raises(DigestMismatchError, match="fetched"):
        ensure_regulation(entry(), cache_dir=tmp_path, opener=lambda a, h: BODY + b" other")
    assert (tmp_path / "sample.xhtml").read_bytes() == BODY + b" edited"


def test_the_cache_folder_can_be_named_by_the_environment(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("REGULATIONS_CACHE_DIR", raising=False)
    assert resolve_cache_dir() == CACHE_DIR
    monkeypatch.setenv("REGULATIONS_CACHE_DIR", str(tmp_path))
    assert resolve_cache_dir() == tmp_path
    assert resolve_cache_dir(tmp_path / "x") == tmp_path / "x"
    (tmp_path / "sample.xhtml").write_bytes(BODY)

    def opener(address: str, headers) -> bytes:
        raise AssertionError("a digest-checked copy named by the environment needs no fetch")

    assert ensure_regulation(entry(), opener=opener) == BODY


def test_one_fetch_waits_at_most_thirty_seconds_a_step_and_ninety_overall():
    assert TIMEOUT_SECONDS == 30
    assert OVERALL_CAP_SECONDS == 90


def test_a_download_that_trickles_past_the_overall_cap_is_given_up(monkeypatch):
    clock = iter([0.0, 10.0, 50.0, 95.0, 96.0])
    monkeypatch.setattr("context.regulations.fetch.time.monotonic", lambda: next(clock))
    chunks = iter([b"a", b"b", b"c", b"d", b""])

    class Slow(_Response):
        def read(self, size: int = -1) -> bytes:
            return next(chunks)

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=0: Slow(200, b""))
    with pytest.raises(RegulationFetchError, match=r"90 seconds"):
        fetch_bytes("https://example.org/x", {})


def test_a_failed_fetch_is_reported_with_the_address(tmp_path: Path):
    def opener(address: str, headers) -> bytes:
        raise OSError("connection refused")

    with pytest.raises(
        RegulationFetchError, match=r"https://example.org/sample.*connection refused"
    ):
        ensure_regulation(entry(), cache_dir=tmp_path, opener=opener)


def test_an_address_that_is_not_https_is_refused_before_any_request():
    with pytest.raises(RegulationFetchError, match="https"):
        fetch_bytes("http://example.org/x", {}, opener=lambda a, h: BODY)


def test_the_manifest_lists_the_three_regulations_with_digests_and_addresses():
    manifest = load_manifest()
    keys = [e.key for e in manifest.regulations]
    assert keys == ["DORA", "AI-ACT", "SS1-23"]
    for e in manifest.regulations:
        assert e.digest.startswith("sha256:") and len(e.digest) == 71
        assert e.address.startswith("https://")
        assert e.size > 100_000
        assert e.fetched == "2026-11-25"
        assert e.terms


def test_the_manifest_records_the_superseded_version_of_the_statement_without_reading_it():
    manifest = load_manifest()
    assert [o.key for o in manifest.other_versions] == ["SS1-23-2023"]
    assert manifest.other_versions[0].digest.startswith("sha256:")


def test_only_the_texts_held_with_the_source_acknowledged_are_in_the_repository():
    """DORA and the AI Act are held as the notice describes; the supervisory statement is not."""
    manifest = load_manifest()
    held = {e.key: e.text_file for e in manifest.regulations if e.text_file}
    assert held == {"DORA": "texts/dora.xhtml", "AI-ACT": "texts/ai-act.xhtml"}
    allowed = {"SOURCES.md", "sources.json", *held.values()}
    stray: list[str] = []
    for path in sorted(REGULATIONS_DIR.rglob("*")):
        relative = path.relative_to(REGULATIONS_DIR)
        if path.is_dir() or relative.parts[0] == "cache":
            continue
        if relative.parts[0] == "expected" and path.suffix == ".json":
            continue
        if relative.as_posix() not in allowed:
            stray.append(relative.as_posix())
    assert stray == []
    for e in manifest.regulations:
        if e.text_file:
            assert digest_bytes((REGULATIONS_DIR / e.text_file).read_bytes()) == e.digest


def test_an_open_text_is_read_from_the_repository_with_no_network_and_its_digest_checked(tmp_path):
    (tmp_path / "held").mkdir()
    (tmp_path / "held" / "sample.xhtml").write_bytes(BODY)
    held = dataclasses.replace(entry(), text_file="held/sample.xhtml")

    def opener(address: str, headers) -> bytes:
        raise AssertionError("an open text held in the repository needs no fetch")

    assert (
        ensure_regulation(held, cache_dir=tmp_path / "cache", opener=opener, root=tmp_path) == BODY
    )
    (tmp_path / "held" / "sample.xhtml").write_bytes(BODY + b" edited")
    with pytest.raises(DigestMismatchError, match="held"):
        ensure_regulation(held, cache_dir=tmp_path / "cache", opener=opener, root=tmp_path)


def test_the_held_texts_carry_the_notice_passages_with_the_address_it_was_read_at():
    for e in load_manifest().regulations:
        if e.text_file:
            assert any("Most of the publications on this website" in p for p in e.notice_passages)
            assert e.notice_address.startswith("https://op.europa.eu/")
            assert e.notice == "see the notice quoted in SOURCES.md"
        else:
            assert e.notice == "" and e.notice_passages == ()


def test_the_statement_reader_needs_poppler_and_the_fetch_says_so_before_fetching(
    monkeypatch, tmp_path
):
    statement = dataclasses.replace(entry(), reader="supervisory_statement")
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(RegulationToolMissingError, match="pdftotext"):
        require_tools(statement)
    require_tools(entry())  # an XHTML act needs no program


def test_the_sources_file_names_every_regulation_and_its_address():
    text = (REGULATIONS_DIR / "SOURCES.md").read_text(encoding="utf-8")
    for e in load_manifest().regulations:
        assert e.address in text
        assert e.digest in text
    assert json.loads((REGULATIONS_DIR / "sources.json").read_text(encoding="utf-8"))


def test_a_live_check_fetches_the_address_and_compares_the_digest(tmp_path: Path):
    assert verify_live(entry(), opener=lambda a, h: BODY) == len(BODY)
    with pytest.raises(DigestMismatchError, match="fetched"):
        verify_live(entry(), opener=lambda a, h: BODY + b" changed")


class _Response:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self, size: int = -1) -> bytes:
        body, self._body = self._body, b""
        return body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def test_a_challenge_page_with_status_202_and_no_body_is_refused_as_unreadable(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=0: _Response(202, b""))
    with pytest.raises(RegulationFetchError, match=r"HTTP 202.*unreadable"):
        fetch_bytes("https://example.org/x", {})


def test_an_empty_body_with_status_200_is_refused(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=0: _Response(200, b""))
    with pytest.raises(RegulationFetchError, match=r"empty body"):
        fetch_bytes("https://example.org/x", {})


def test_a_status_200_with_a_body_is_returned(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=0: _Response(200, BODY))
    assert fetch_bytes("https://example.org/x", {}) == BODY
