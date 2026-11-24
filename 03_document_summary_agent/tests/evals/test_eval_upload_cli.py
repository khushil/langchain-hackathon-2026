"""Tests for the command that uploads the two datasets, on a fake client."""

import uuid
from types import SimpleNamespace

from evals import build_dataset, upload


class FakeClient:
    def __init__(self):
        self.datasets, self.examples = [], {}

    def list_datasets(self, *, dataset_name=None, **kwargs):
        return iter([d for d in self.datasets if dataset_name in (None, d.name)])

    def create_dataset(self, dataset_name, *, description=None, metadata=None, **kwargs):
        dataset = SimpleNamespace(id=uuid.uuid4(), name=dataset_name, metadata=metadata)
        self.datasets.append(dataset)
        self.examples[dataset.id] = []
        return dataset

    def create_examples(self, *, dataset_id, examples, **kwargs):
        self.examples[dataset_id].extend(examples)

    def list_examples(self, *, dataset_id, **kwargs):
        return iter(self.examples[dataset_id])


def test_the_first_run_creates_both_datasets_and_prints_their_ids_and_counts(capsys):
    client = FakeClient()
    assert upload.main([], client=client) == 0
    out = capsys.readouterr().out
    assert [d.name for d in client.datasets] == [upload.SECTIONS_NAME, upload.DOCUMENT_NAME]
    assert [len(client.examples[d.id]) for d in client.datasets] == [10, 1]
    assert f"{upload.SECTIONS_NAME} id={client.datasets[0].id} examples=10 added=10" in out
    assert f"{upload.DOCUMENT_NAME} id={client.datasets[1].id} examples=1 added=1" in out


def test_the_second_run_adds_nothing_and_says_so(capsys):
    client = FakeClient()
    upload.main([], client=client)
    capsys.readouterr()
    assert upload.main([], client=client) == 0
    out = capsys.readouterr().out
    assert out.count("nothing added") == 2
    assert [len(client.examples[d.id]) for d in client.datasets] == [10, 1]


def test_a_dataset_that_differs_is_refused_with_exit_one(capsys):
    client = FakeClient()
    client.create_dataset(upload.SECTIONS_NAME, metadata={"content_sha256": "0" * 64})
    assert upload.main([], client=client) == 1
    assert "FAIL" in capsys.readouterr().out
    assert len(client.datasets) == 1


def test_nothing_is_uploaded_when_the_files_on_disk_are_out_of_date(tmp_path, capsys):
    client = FakeClient()
    assert upload.main(["--data-dir", str(tmp_path)], client=client) == 1
    assert "missing" in capsys.readouterr().out
    assert client.datasets == []


def test_without_a_key_the_command_fails_before_any_call(monkeypatch, capsys):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_KEY", raising=False)
    assert upload.main([]) == 1
    assert "no LangSmith key" in capsys.readouterr().out


def test_the_key_is_read_from_either_name_and_never_printed(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_KEY", "secret-value")
    assert upload.read_key() == "secret-value"
    monkeypatch.setenv("LANGSMITH_API_KEY", "other-value")
    assert upload.read_key() == "other-value"


def test_the_examples_uploaded_are_the_ones_on_disk():
    client = FakeClient()
    upload.main([], client=client)
    on_disk = build_dataset.read_examples("sections.jsonl")
    sent = client.examples[client.datasets[0].id]
    assert [e["metadata"]["key"] for e in sent] == [e["key"] for e in on_disk]
    assert sent[6]["outputs"] == on_disk[6]["reference_outputs"]
