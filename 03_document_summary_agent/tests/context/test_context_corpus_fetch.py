"""Tests of fetching a corpus's published documents that the repository does not hold."""

import pytest
from corpus_support import make_corpus, published_entry, written_entry

from context.corpus import CorpusDigestError, CorpusManifestError, read_corpus
from context.corpus_fetch import CorpusFetchError, fetch_corpus, main

PDF_A = b"%PDF-1.7 the first published document"
PDF_B = b"%PDF-1.7 the second published document"
POLICY = b"# A policy\n\n## 1. Purpose\n\n1.1 The bank keeps a register.\n"


class FakeOpener:
    """Serve fixed bytes for each address and record every address asked for."""

    def __init__(self, served: dict[str, bytes]):
        self.served = served
        self.asked: list[str] = []

    def __call__(self, address: str) -> bytes:
        self.asked.append(address)
        if address not in self.served:
            raise CorpusFetchError(f"{address} could not be fetched: not served")
        return self.served[address]


def _bank(tmp_path, files=None):
    documents = [
        published_entry("PUB-A", "a.pdf", PDF_A),
        published_entry("PUB-B", "b.pdf", PDF_B),
    ]
    return make_corpus(tmp_path, "bank", files or {}, documents, origin="published")


def test_fetch_corpus_fetches_each_fetch_only_document_and_the_corpus_then_reads(tmp_path):
    folder = _bank(tmp_path)
    opener = FakeOpener({"https://example.org/a.pdf": PDF_A, "https://example.org/b.pdf": PDF_B})
    result = fetch_corpus("bank", root=tmp_path, opener=opener)
    assert result.fetched == ["PUB-A", "PUB-B"]
    assert result.present == []
    assert result.committed == []
    assert result.line == (
        "bank: 2 of 2 fetch-only documents were fetched, 0 already present, 0 committed"
    )
    assert (folder / "fetched" / "a.pdf").read_bytes() == PDF_A
    assert [d.data for d in read_corpus("bank", root=tmp_path).documents] == [PDF_A, PDF_B]


def test_fetch_corpus_leaves_a_present_copy_whose_digest_matches(tmp_path):
    _bank(tmp_path, files={"fetched/a.pdf": PDF_A})
    opener = FakeOpener({"https://example.org/b.pdf": PDF_B})
    result = fetch_corpus("bank", root=tmp_path, opener=opener)
    assert result.fetched == ["PUB-B"]
    assert result.present == ["PUB-A"]
    assert opener.asked == ["https://example.org/b.pdf"]


def test_fetch_corpus_refuses_bytes_whose_digest_differs_and_writes_nothing(tmp_path):
    folder = _bank(tmp_path)
    opener = FakeOpener(
        {
            "https://example.org/a.pdf": b"%PDF the publisher changed it",
            "https://example.org/b.pdf": PDF_B,
        }
    )
    with pytest.raises(CorpusDigestError, match="PUB-A.*https://example.org/a.pdf"):
        fetch_corpus("bank", root=tmp_path, opener=opener)
    assert not (folder / "fetched" / "a.pdf").exists()


def test_fetch_corpus_replaces_a_present_copy_whose_digest_differs(tmp_path):
    folder = _bank(tmp_path, files={"fetched/a.pdf": b"%PDF a stale copy"})
    opener = FakeOpener({"https://example.org/a.pdf": PDF_A, "https://example.org/b.pdf": PDF_B})
    result = fetch_corpus("bank", root=tmp_path, opener=opener)
    assert result.fetched == ["PUB-A", "PUB-B"]
    assert (folder / "fetched" / "a.pdf").read_bytes() == PDF_A


def test_fetch_corpus_never_fetches_a_committed_document(tmp_path):
    documents = [written_entry("POL-1", "policy.md", POLICY)]
    make_corpus(tmp_path, "example", {"policy.md": POLICY}, documents)
    opener = FakeOpener({})
    result = fetch_corpus("example", root=tmp_path, opener=opener)
    assert result.committed == ["POL-1"]
    assert result.fetched == []
    assert opener.asked == []


def test_fetch_corpus_reports_an_address_that_cannot_be_fetched(tmp_path):
    _bank(tmp_path)
    opener = FakeOpener({"https://example.org/a.pdf": PDF_A})
    with pytest.raises(CorpusFetchError, match="https://example.org/b.pdf"):
        fetch_corpus("bank", root=tmp_path, opener=opener)


def test_fetch_corpus_refuses_a_manifest_that_does_not_validate(tmp_path):
    make_corpus(tmp_path, "bank", {}, [], origin="published")
    with pytest.raises(CorpusManifestError, match="lists no document"):
        fetch_corpus("bank", root=tmp_path, opener=FakeOpener({}))


def test_main_prints_the_line_and_returns_zero(tmp_path, capsys):
    _bank(tmp_path)
    opener = FakeOpener({"https://example.org/a.pdf": PDF_A, "https://example.org/b.pdf": PDF_B})
    assert main(["bank"], root=tmp_path, opener=opener) == 0
    assert "bank: 2 of 2 fetch-only documents were fetched" in capsys.readouterr().out


def test_main_reports_a_failure_in_words_and_returns_one(tmp_path, capsys):
    _bank(tmp_path)
    opener = FakeOpener(
        {"https://example.org/a.pdf": b"%PDF wrong", "https://example.org/b.pdf": PDF_B}
    )
    assert main(["bank"], root=tmp_path, opener=opener) == 1
    err = capsys.readouterr().err
    assert "PUB-A" in err
    assert "Traceback" not in err
