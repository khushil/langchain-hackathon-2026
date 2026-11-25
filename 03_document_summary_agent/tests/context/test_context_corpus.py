"""Tests of reading a corpus: a folder of documents and the manifest that accounts for each one."""

import json

import pytest
from corpus_support import make_corpus, published_entry, written_entry

from context.corpus import (
    POLICIES_DIR,
    CorpusDigestError,
    CorpusFileError,
    CorpusManifestError,
    CorpusNotFoundError,
    DocumentNotFetchedError,
    list_corpora,
    read_corpus,
)
from context.errors import ContextError
from fsi_common.ids import digest_bytes
from utils import PROJECT_ROOT

HMB = "harbour-mutual-bank"
POLICY = b"# A policy\n\n## 1. Purpose\n\n1.1 The bank keeps a register.\n"
STANDARD = b"# A standard\n\n## 1. Scope\n\n1.1 The standard applies to every supplier.\n"
PDF = b"%PDF-1.7 published bytes"


def _two_documents(tmp_path, **changes):
    files = {"policy.md": POLICY, "standard.md": STANDARD}
    documents = [
        written_entry("POL-1", "policy.md", POLICY),
        written_entry("STD-1", "standard.md", STANDARD),
    ]
    make_corpus(tmp_path, "example", files, documents, **changes)
    return documents


# The written corpus in the repository.


def test_list_corpora_names_the_harbour_mutual_bank_set():
    assert HMB in list_corpora()


def test_read_corpus_reads_every_document_of_the_harbour_mutual_bank_set():
    manifest = json.loads((POLICIES_DIR / HMB / "manifest.json").read_text(encoding="utf-8"))
    corpus = read_corpus(HMB)
    assert len(manifest["documents"]) >= 6
    assert [d.entry.id for d in corpus.documents] == [d["id"] for d in manifest["documents"]]
    total = len(manifest["documents"])
    assert corpus.line == f"{HMB}: {total} of {total} documents read, every digest checked"
    for document in corpus.documents:
        path = POLICIES_DIR / HMB / document.entry.file
        assert document.data == path.read_bytes()
        assert document.source.digest == digest_bytes(path.read_bytes())
        assert document.source.key == document.entry.id
        assert document.source.kind == "policy_document"
        assert document.source.title == document.entry.title
        assert document.source.locator == path.relative_to(PROJECT_ROOT.parent).as_posix()
        assert document.entry.holding == "committed"


def test_read_corpus_twice_gives_identical_sources():
    first, second = read_corpus(HMB), read_corpus(HMB)
    assert [d.source.to_json() for d in first.documents] == [
        d.source.to_json() for d in second.documents
    ]


def test_read_corpus_harbour_mutual_bank_is_written_and_names_its_terms():
    corpus = read_corpus(HMB)
    assert corpus.manifest.origin == "written"
    assert corpus.manifest.institution == "Harbour Mutual Bank"
    for document in corpus.documents:
        assert document.entry.date_kind == "written"
        assert "fictional" in document.entry.terms.lower()
        assert document.source.terms.startswith(document.entry.terms)


# A corpus folder built for each test.


def test_read_corpus_reads_a_written_corpus_in_manifest_order(tmp_path):
    _two_documents(tmp_path)
    corpus = read_corpus("example", root=tmp_path)
    assert [d.entry.id for d in corpus.documents] == ["POL-1", "STD-1"]
    assert corpus.document("STD-1").data == STANDARD
    assert corpus.document("NONE") is None
    assert corpus.line == "example: 2 of 2 documents read, every digest checked"


def test_corpus_errors_are_context_errors():
    for error in (
        CorpusNotFoundError,
        CorpusManifestError,
        CorpusFileError,
        CorpusDigestError,
        DocumentNotFetchedError,
    ):
        assert issubclass(error, ContextError)


def test_read_corpus_unknown_corpus_is_named(tmp_path):
    with pytest.raises(CorpusNotFoundError, match="no-such-corpus"):
        read_corpus("no-such-corpus", root=tmp_path)


def test_read_corpus_refuses_a_name_that_leaves_the_corpora_folder(tmp_path):
    with pytest.raises(CorpusNotFoundError, match=r"\.\./outside"):
        read_corpus("../outside", root=tmp_path)


def test_read_corpus_refuses_a_digest_that_differs_and_names_both(tmp_path):
    wrong = digest_bytes(b"other bytes")
    files = {"policy.md": POLICY}
    make_corpus(
        tmp_path, "example", files, [written_entry("POL-1", "policy.md", POLICY, digest=wrong)]
    )
    with pytest.raises(CorpusDigestError, match="POL-1") as raised:
        read_corpus("example", root=tmp_path)
    assert wrong in str(raised.value)
    assert digest_bytes(POLICY) in str(raised.value)


def test_read_corpus_refuses_a_file_the_manifest_does_not_list(tmp_path):
    files = {"policy.md": POLICY, "stray.md": b"a stray note"}
    make_corpus(tmp_path, "example", files, [written_entry("POL-1", "policy.md", POLICY)])
    with pytest.raises(CorpusFileError, match="stray.md"):
        read_corpus("example", root=tmp_path)


def test_read_corpus_refuses_a_stray_file_in_a_subfolder(tmp_path):
    files = {"policy.md": POLICY, "old/policy.md": POLICY + b"older"}
    make_corpus(tmp_path, "example", files, [written_entry("POL-1", "policy.md", POLICY)])
    with pytest.raises(CorpusFileError, match="old/policy.md"):
        read_corpus("example", root=tmp_path)


def test_read_corpus_allows_its_readme_and_ignore_file(tmp_path):
    files = {"policy.md": POLICY, "README.md": b"# About\n", ".gitignore": b"fetched/\n"}
    make_corpus(tmp_path, "example", files, [written_entry("POL-1", "policy.md", POLICY)])
    assert len(read_corpus("example", root=tmp_path).documents) == 1


def test_read_corpus_refuses_a_listed_file_that_is_missing(tmp_path):
    documents = [
        written_entry("POL-1", "policy.md", POLICY),
        written_entry("STD-1", "standard.md", STANDARD),
    ]
    make_corpus(tmp_path, "example", {"policy.md": POLICY}, documents)
    with pytest.raises(CorpusFileError, match="STD-1.*standard.md"):
        read_corpus("example", root=tmp_path)


@pytest.mark.parametrize("field", ["id", "file", "digest"])
def test_read_corpus_refuses_a_repeated_id_file_or_digest(tmp_path, field):
    first = written_entry("POL-1", "policy.md", POLICY)
    second = {**written_entry("STD-1", "standard.md", STANDARD), field: first[field]}
    files = {"policy.md": POLICY, "standard.md": STANDARD}
    make_corpus(tmp_path, "example", files, [first, second])
    with pytest.raises(CorpusManifestError, match=f"{field}.*twice"):
        read_corpus("example", root=tmp_path)


@pytest.mark.parametrize("file", ["../policy.md", "sub/../../policy.md", "/etc/hostname"])
def test_read_corpus_refuses_a_file_path_that_leaves_the_folder(tmp_path, file):
    make_corpus(tmp_path, "example", {}, [written_entry("POL-1", file, POLICY)])
    with pytest.raises(CorpusManifestError, match="leaves the corpus folder"):
        read_corpus("example", root=tmp_path)


@pytest.mark.parametrize("file", ["manifest.json", "README.md", "fetched/policy.md"])
def test_read_corpus_refuses_a_document_file_that_names_a_reserved_place(tmp_path, file):
    make_corpus(tmp_path, "example", {}, [written_entry("POL-1", file, POLICY)])
    with pytest.raises(CorpusManifestError, match="reserved"):
        read_corpus("example", root=tmp_path)


def test_read_corpus_refuses_a_manifest_that_is_not_json(tmp_path):
    make_corpus(tmp_path, "example", {}, [], manifest_text="{ not json")
    with pytest.raises(CorpusManifestError, match="manifest.json.*not JSON"):
        read_corpus("example", root=tmp_path)


def test_read_corpus_refuses_a_missing_manifest(tmp_path):
    (tmp_path / "example").mkdir()
    with pytest.raises(CorpusManifestError, match="no manifest.json"):
        read_corpus("example", root=tmp_path)


@pytest.mark.parametrize("field", ["digest", "terms", "date", "source"])
def test_read_corpus_refuses_an_entry_missing_a_field_and_names_it(tmp_path, field):
    entry = written_entry("POL-1", "policy.md", POLICY)
    del entry[field]
    make_corpus(tmp_path, "example", {"policy.md": POLICY}, [entry])
    with pytest.raises(CorpusManifestError, match=field):
        read_corpus("example", root=tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("digest", "sha256:abc"),
        ("date", "2026-02-30"),
        ("format", "docx"),
        ("terms", "   "),
        ("date_kind", "copied"),
    ],
)
def test_read_corpus_refuses_an_entry_with_a_bad_value(tmp_path, field, value):
    entry = written_entry("POL-1", "policy.md", POLICY, **{field: value})
    make_corpus(tmp_path, "example", {"policy.md": POLICY}, [entry])
    with pytest.raises(CorpusManifestError, match=field):
        read_corpus("example", root=tmp_path)


def test_read_corpus_refuses_a_manifest_with_no_documents(tmp_path):
    make_corpus(tmp_path, "example", {}, [])
    with pytest.raises(CorpusManifestError, match="lists no document"):
        read_corpus("example", root=tmp_path)


def test_read_corpus_refuses_a_manifest_named_for_another_corpus(tmp_path):
    files = {"policy.md": POLICY}
    entry = written_entry("POL-1", "policy.md", POLICY)
    make_corpus(tmp_path, "example", files, [entry], corpus="another")
    with pytest.raises(CorpusManifestError, match="another.*example"):
        read_corpus("example", root=tmp_path)


@pytest.mark.parametrize(
    "changes",
    [{"holding": "fetch"}, {"date_kind": "fetched"}],
)
def test_read_corpus_refuses_a_written_document_recorded_as_fetched(tmp_path, changes):
    entry = written_entry("POL-1", "policy.md", POLICY, **changes)
    make_corpus(tmp_path, "example", {"policy.md": POLICY}, [entry])
    with pytest.raises(CorpusManifestError, match="written"):
        read_corpus("example", root=tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", "Written for this repository"),
        ("source", "http://example.org/a.pdf"),
        ("date_kind", "written"),
    ],
)
def test_read_corpus_refuses_a_published_document_without_its_address_or_terms(
    tmp_path, field, value
):
    entry = published_entry("PUB-1", "a.pdf", PDF, **{field: value})
    make_corpus(tmp_path, "bank", {}, [entry], origin="published")
    with pytest.raises(CorpusManifestError, match="published"):
        read_corpus("bank", root=tmp_path)


def test_read_corpus_refuses_a_committed_published_document_with_no_address_for_its_terms(tmp_path):
    entry = published_entry("PUB-1", "a.pdf", PDF, holding="committed", terms_address=None)
    make_corpus(tmp_path, "bank", {"a.pdf": PDF}, [entry], origin="published")
    with pytest.raises(CorpusManifestError, match="committed.*terms"):
        read_corpus("bank", root=tmp_path)


def test_read_corpus_reads_a_fetch_only_document_whose_terms_have_no_address(tmp_path):
    entry = published_entry("PUB-1", "a.pdf", PDF, terms_address=None, terms="No terms found")
    make_corpus(tmp_path, "bank", {"fetched/a.pdf": PDF}, [entry], origin="published")
    document = read_corpus("bank", root=tmp_path).document("PUB-1")
    assert document.source.terms == "No terms found"


# Published documents the corpus does not hold.


def test_read_corpus_names_the_fetch_command_for_a_document_not_fetched(tmp_path):
    entry = published_entry("PUB-1", "a.pdf", PDF)
    make_corpus(tmp_path, "bank", {}, [entry], origin="published")
    with pytest.raises(DocumentNotFetchedError, match="PUB-1") as raised:
        read_corpus("bank", root=tmp_path)
    assert "python -m context.corpus_fetch bank" in str(raised.value)
    assert "https://example.org/a.pdf" in str(raised.value)


def test_read_corpus_reads_a_fetched_copy_whose_digest_matches(tmp_path):
    entry = published_entry("PUB-1", "a.pdf", PDF)
    make_corpus(tmp_path, "bank", {"fetched/a.pdf": PDF}, [entry], origin="published")
    corpus = read_corpus("bank", root=tmp_path)
    document = corpus.document("PUB-1")
    assert document.data == PDF
    assert document.source.locator == "https://example.org/a.pdf"
    assert "https://example.org/legal" in document.source.terms
    assert document.path == tmp_path / "bank" / "fetched" / "a.pdf"


def test_read_corpus_refuses_a_fetched_copy_whose_digest_differs(tmp_path):
    entry = published_entry("PUB-1", "a.pdf", PDF)
    files = {"fetched/a.pdf": b"%PDF changed since the digest was taken"}
    make_corpus(tmp_path, "bank", files, [entry], origin="published")
    with pytest.raises(CorpusDigestError, match="PUB-1"):
        read_corpus("bank", root=tmp_path)


def test_read_corpus_refuses_a_fetched_file_no_entry_accounts_for(tmp_path):
    entry = published_entry("PUB-1", "a.pdf", PDF)
    files = {"fetched/a.pdf": PDF, "fetched/b.pdf": b"%PDF another"}
    make_corpus(tmp_path, "bank", files, [entry], origin="published")
    with pytest.raises(CorpusFileError, match="fetched/b.pdf"):
        read_corpus("bank", root=tmp_path)


def test_read_corpus_refuses_a_committed_document_placed_in_the_fetched_folder(tmp_path):
    files = {"fetched/policy.md": POLICY}
    make_corpus(tmp_path, "example", files, [written_entry("POL-1", "policy.md", POLICY)])
    with pytest.raises(CorpusFileError, match="POL-1.*policy.md"):
        read_corpus("example", root=tmp_path)


def test_read_corpus_refuses_a_fetch_only_document_placed_in_the_corpus_folder(
    tmp_path,
):
    entry = published_entry("PUB-1", "a.pdf", PDF)
    make_corpus(tmp_path, "bank", {"a.pdf": PDF}, [entry], origin="published")
    with pytest.raises(CorpusFileError, match="a.pdf"):
        read_corpus("bank", root=tmp_path)


def test_read_corpus_reads_a_published_document_whose_terms_allow_it_to_be_committed(tmp_path):
    entry = published_entry("PUB-1", "a.pdf", PDF, holding="committed")
    make_corpus(tmp_path, "bank", {"a.pdf": PDF}, [entry], origin="published")
    document = read_corpus("bank", root=tmp_path).document("PUB-1")
    assert document.data == PDF
    assert document.source.locator == "https://example.org/a.pdf"


def test_list_corpora_lists_only_folders_with_a_manifest_in_name_order(tmp_path):
    _two_documents(tmp_path)
    make_corpus(tmp_path, "alpha", {"policy.md": POLICY}, [written_entry("P", "policy.md", POLICY)])
    (tmp_path / "empty-folder").mkdir()
    (tmp_path / "loose.txt").write_text("not a corpus", encoding="utf-8")
    assert list_corpora(root=tmp_path) == ["alpha", "example"]


def test_list_corpora_of_a_missing_folder_is_empty(tmp_path):
    assert list_corpora(root=tmp_path / "absent") == []
