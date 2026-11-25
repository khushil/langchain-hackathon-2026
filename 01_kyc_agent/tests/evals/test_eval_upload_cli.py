"""The command that uploads the dataset, on a fake client."""

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


def test_the_first_run_creates_the_dataset_and_prints_its_id_and_count(capsys):
    client = FakeClient()
    assert upload.main([], client=client) == 0
    out = capsys.readouterr().out
    assert [d.name for d in client.datasets] == [upload.DATASET_NAME]
    assert len(client.examples[client.datasets[0].id]) == 25
    assert f"{upload.DATASET_NAME} id={client.datasets[0].id} examples=25 added=25" in out


def test_the_second_run_adds_nothing_and_says_so(capsys):
    client = FakeClient()
    upload.main([], client=client)
    capsys.readouterr()
    assert upload.main([], client=client) == 0
    assert "nothing added" in capsys.readouterr().out
    assert len(client.examples[client.datasets[0].id]) == 25


def test_a_dataset_that_differs_is_refused_with_exit_one(capsys):
    client = FakeClient()
    client.create_dataset(upload.DATASET_NAME, metadata={"content_sha256": "0" * 64})
    assert upload.main([], client=client) == 1
    assert "FAIL" in capsys.readouterr().out
    assert client.examples[client.datasets[0].id] == []


def test_nothing_is_uploaded_when_the_file_on_disk_is_out_of_date(tmp_path, capsys):
    client = FakeClient()
    assert upload.main(["--data-dir", str(tmp_path)], client=client) == 1
    assert "missing" in capsys.readouterr().out
    assert client.datasets == []


def test_without_a_key_the_command_fails_before_any_call(monkeypatch, capsys):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_KEY", raising=False)
    assert upload.main([]) == 1
    assert "no LangSmith key" in capsys.readouterr().out


def test_the_key_is_read_from_either_name(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_KEY", "a-value-for-the-test")
    assert upload.read_key() == "a-value-for-the-test"
    monkeypatch.setenv("LANGSMITH_API_KEY", "another-value")
    assert upload.read_key() == "another-value"


def test_the_examples_uploaded_are_the_ones_on_disk_with_the_labels_as_outputs():
    client = FakeClient()
    upload.main([], client=client)
    on_disk = build_dataset.read_examples()
    sent = client.examples[client.datasets[0].id]
    assert [e["metadata"]["key"] for e in sent] == [e["key"] for e in on_disk]
    assert sent[17]["outputs"]["risk_level"] == "low"
    assert sent[17]["outputs"]["edge_case"] is True


def test_the_description_says_the_labels_are_the_starters():
    assert "starter" in upload.DESCRIPTION
