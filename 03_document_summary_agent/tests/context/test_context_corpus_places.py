"""Tests of where a corpus and its documents are found: settings, text twins and named records."""

import os

import pytest
from corpus_support import make_corpus, published_entry, written_entry

from context.corpus import (
    CORPORA_SETTING,
    POLICIES_DIR,
    CorpusDigestError,
    CorpusFileError,
    CorpusManifestError,
    CorpusNotFoundError,
    DocumentNotFetchedError,
    corpus_roots,
    list_corpora,
    read_corpus,
)
from context.corpus_fetch import fetch_corpus
from fsi_common.ids import digest_bytes

PDF = b"%PDF-1.7 published bytes"
TEXT = b"The published document as text.\n"
POLICY = b"# A policy\n\n## 1. Purpose\n\n1.1 The bank keeps a register.\n"
SETTING = "TEST_POLICY_DOCUMENTS_DIR"


def _bank(root, entries, **changes):
    return make_corpus(root, "bank", {}, entries, origin="published", **changes)


# Documents read in place, through the folder a setting names.


def test_read_corpus_reads_a_fetch_only_document_from_the_folder_its_setting_names(
    tmp_path, monkeypatch
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.pdf").write_bytes(PDF)
    (outside / "another-institution.pdf").write_bytes(b"%PDF not this corpus's")
    _bank(tmp_path / "corpora", [published_entry("PUB-1", "a.pdf", PDF)], documents_setting=SETTING)
    monkeypatch.setenv(SETTING, str(outside))
    document = read_corpus("bank", root=tmp_path / "corpora").document("PUB-1")
    assert document.path == outside / "a.pdf"
    assert document.data == PDF
    assert not (tmp_path / "corpora" / "bank" / "fetched").exists()


def test_read_corpus_names_the_setting_when_a_document_is_not_in_its_folder(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    _bank(tmp_path / "corpora", [published_entry("PUB-1", "a.pdf", PDF)], documents_setting=SETTING)
    monkeypatch.setenv(SETTING, str(outside))
    with pytest.raises(DocumentNotFetchedError, match=SETTING):
        read_corpus("bank", root=tmp_path / "corpora")


def test_read_corpus_uses_the_fetched_folder_when_the_setting_is_not_set(tmp_path, monkeypatch):
    monkeypatch.delenv(SETTING, raising=False)
    entry = published_entry("PUB-1", "a.pdf", PDF)
    make_corpus(
        tmp_path,
        "bank",
        {"fetched/a.pdf": PDF},
        [entry],
        origin="published",
        documents_setting=SETTING,
    )
    assert read_corpus("bank", root=tmp_path).document("PUB-1").data == PDF


def test_read_corpus_refuses_a_setting_that_names_no_folder(tmp_path, monkeypatch):
    _bank(tmp_path, [published_entry("PUB-1", "a.pdf", PDF)], documents_setting=SETTING)
    monkeypatch.setenv(SETTING, str(tmp_path / "absent"))
    with pytest.raises(CorpusFileError, match=f"{SETTING}.*absent"):
        read_corpus("bank", root=tmp_path)


def test_read_corpus_refuses_a_setting_name_that_is_not_an_environment_name(tmp_path):
    _bank(tmp_path, [published_entry("PUB-1", "a.pdf", PDF)], documents_setting="lower case")
    with pytest.raises(CorpusManifestError, match="documents_setting"):
        read_corpus("bank", root=tmp_path)


def test_fetch_corpus_writes_into_the_folder_the_setting_names(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    _bank(tmp_path / "corpora", [published_entry("PUB-1", "a.pdf", PDF)], documents_setting=SETTING)
    monkeypatch.setenv(SETTING, str(outside))
    result = fetch_corpus("bank", root=tmp_path / "corpora", opener=lambda address: PDF)
    assert result.fetched == ["PUB-1"]
    assert (outside / "a.pdf").read_bytes() == PDF
    assert not (tmp_path / "corpora" / "bank" / "fetched").exists()


# Corpus folders outside the repository, through the corpora setting.


def test_corpus_roots_are_the_repository_folder_then_each_folder_the_setting_names(
    tmp_path, monkeypatch
):
    first, second = tmp_path / "first", tmp_path / "second"
    monkeypatch.setenv(CORPORA_SETTING, os.pathsep.join([str(first), str(second)]))
    assert corpus_roots() == [POLICIES_DIR, first, second]
    monkeypatch.delenv(CORPORA_SETTING)
    assert corpus_roots() == [POLICIES_DIR]


def test_read_corpus_finds_a_corpus_in_a_folder_the_setting_names(tmp_path, monkeypatch):
    private = tmp_path / "private"
    entries = [written_entry("P", "policy.md", POLICY)]
    make_corpus(private, "kept-private", {"policy.md": POLICY}, entries)
    monkeypatch.setenv(CORPORA_SETTING, str(private))
    assert "kept-private" in list_corpora()
    assert "harbour-mutual-bank" in list_corpora()
    assert read_corpus("kept-private").document("P").data == POLICY


def test_read_corpus_refuses_a_name_found_in_two_corpus_folders(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    for root in (first, second):
        make_corpus(root, "twice", {"policy.md": POLICY}, [written_entry("P", "policy.md", POLICY)])
    monkeypatch.setenv(CORPORA_SETTING, os.pathsep.join([str(first), str(second)]))
    with pytest.raises(CorpusNotFoundError, match="twice.*two"):
        read_corpus("twice")


# Text twins of published documents.


def test_read_corpus_reads_a_text_twin_whose_digest_matches(tmp_path):
    entry = published_entry(
        "PUB-1", "a.pdf", PDF, text_file="a.txt", text_digest=digest_bytes(TEXT)
    )
    make_corpus(
        tmp_path, "bank", {"fetched/a.pdf": PDF, "fetched/a.txt": TEXT}, [entry], origin="published"
    )
    document = read_corpus("bank", root=tmp_path).document("PUB-1")
    assert document.text == TEXT.decode("utf-8")
    assert document.text_path == tmp_path / "bank" / "fetched" / "a.txt"


def test_read_corpus_refuses_a_text_twin_whose_digest_differs(tmp_path):
    entry = published_entry(
        "PUB-1", "a.pdf", PDF, text_file="a.txt", text_digest=digest_bytes(b"other text")
    )
    make_corpus(
        tmp_path, "bank", {"fetched/a.pdf": PDF, "fetched/a.txt": TEXT}, [entry], origin="published"
    )
    with pytest.raises(CorpusDigestError, match="PUB-1.*a.txt"):
        read_corpus("bank", root=tmp_path)


def test_read_corpus_refuses_a_text_file_without_its_digest(tmp_path):
    entry = published_entry("PUB-1", "a.pdf", PDF, text_file="a.txt")
    _bank(tmp_path, [entry])
    with pytest.raises(CorpusManifestError, match="text_file and text_digest"):
        read_corpus("bank", root=tmp_path)


def test_read_corpus_gives_a_markdown_document_its_own_text(tmp_path):
    entries = [written_entry("P", "policy.md", POLICY)]
    make_corpus(tmp_path, "example", {"policy.md": POLICY}, entries)
    document = read_corpus("example", root=tmp_path).document("P")
    assert document.text == POLICY.decode("utf-8")
    assert document.text_path == document.path


def test_read_corpus_has_no_text_for_a_pdf_without_a_twin(tmp_path):
    make_corpus(
        tmp_path,
        "bank",
        {"fetched/a.pdf": PDF},
        [published_entry("PUB-1", "a.pdf", PDF)],
        origin="published",
    )
    document = read_corpus("bank", root=tmp_path).document("PUB-1")
    assert document.text is None
    assert document.text_path is None


# Records the manifest keeps about the corpus as a whole.


def test_read_corpus_keeps_named_documents_inferred_relations_and_the_benchmark_note(tmp_path):
    entries = [
        published_entry("OLD", "old.pdf", PDF, part="The bank's own documents"),
        published_entry("NEW", "new.pdf", PDF + b"new", part="The group's documents"),
    ]
    files = {"fetched/old.pdf": PDF, "fetched/new.pdf": PDF + b"new"}
    make_corpus(
        tmp_path,
        "bank",
        files,
        entries,
        origin="published",
        benchmark="The institution is not one the regulations bind; each is read as a benchmark",
        named_not_read=[{"title": "Policy for outsourcing", "named_in": "OLD"}],
        inferred_relations=[
            {"relation": "supersedes", "document": "NEW", "other": "OLD", "basis": "A brand moved"}
        ],
    )
    manifest = read_corpus("bank", root=tmp_path).manifest
    assert manifest.benchmark.startswith("The institution is not one")
    assert manifest.named_not_read[0].named_in == "OLD"
    assert manifest.named_not_read[0].status == "not published"
    assert manifest.inferred_relations[0].other == "OLD"
    assert manifest.documents[0].part == "The bank's own documents"


@pytest.mark.parametrize(
    "changes",
    [
        {"named_not_read": [{"title": "A policy", "named_in": "NONE"}]},
        {
            "inferred_relations": [
                {"relation": "supersedes", "document": "PUB-1", "other": "NONE", "basis": "b"}
            ]
        },
        {
            "inferred_relations": [
                {"relation": "supersedes", "document": "PUB-1", "other": "PUB-1", "basis": "b"}
            ]
        },
    ],
)
def test_read_corpus_refuses_a_corpus_record_that_names_no_listed_document(tmp_path, changes):
    _bank(tmp_path, [published_entry("PUB-1", "a.pdf", PDF)], **changes)
    with pytest.raises(CorpusManifestError, match="NONE|itself"):
        read_corpus("bank", root=tmp_path)


def test_read_corpus_refuses_a_named_document_status_it_does_not_know(tmp_path):
    named = [{"title": "A policy", "named_in": "PUB-1", "status": "lost"}]
    _bank(tmp_path, [published_entry("PUB-1", "a.pdf", PDF)], named_not_read=named)
    with pytest.raises(CorpusManifestError, match="status"):
        read_corpus("bank", root=tmp_path)
