"""Tests for the dataset upload, on a fake of the LangSmith client."""

import uuid
from types import SimpleNamespace

import pytest

from fsi_common.evals.upload import (
    DatasetDiffersError,
    DatasetIncompleteError,
    DatasetNameError,
    content_digest,
    to_langsmith_examples,
    upload_dataset,
)


class FakeClient:
    """Holds datasets and their examples in memory and records each call that writes."""

    def __init__(self):
        self.datasets = []
        self.examples = {}
        self.writes = []

    def list_datasets(self, *, dataset_name=None, **kwargs):
        return iter([d for d in self.datasets if dataset_name in (None, d.name)])

    def create_dataset(self, dataset_name, *, description=None, metadata=None, **kwargs):
        dataset = SimpleNamespace(
            id=uuid.uuid4(), name=dataset_name, description=description, metadata=metadata
        )
        self.datasets.append(dataset)
        self.examples[dataset.id] = []
        self.writes.append(("create_dataset", dataset_name))
        return dataset

    def create_examples(self, *, dataset_id, examples, **kwargs):
        self.examples[dataset_id].extend(examples)
        self.writes.append(("create_examples", len(examples)))

    def list_examples(self, *, dataset_id, **kwargs):
        return iter(self.examples[dataset_id])


EXAMPLES = [
    {"key": "a", "inputs": {"x": 1}, "reference_outputs": {"y": 2}, "metadata": {"m": "n"}},
    {"key": "b", "inputs": {"x": 3}, "reference_outputs": {"y": 4}, "metadata": {"m": "n"}},
]


def test_examples_are_mapped_to_the_shape_langsmith_takes():
    assert to_langsmith_examples(EXAMPLES)[0] == {
        "inputs": {"x": 1},
        "outputs": {"y": 2},
        "metadata": {"m": "n", "key": "a"},
    }


def test_the_digest_ignores_key_order_and_changes_with_content():
    reordered = [{"metadata": e["metadata"], **e} for e in EXAMPLES]
    assert content_digest(EXAMPLES) == content_digest(reordered)
    changed = [dict(EXAMPLES[0], inputs={"x": 9}), EXAMPLES[1]]
    assert content_digest(changed) != content_digest(EXAMPLES)


def test_the_first_upload_creates_the_dataset_and_adds_every_example():
    client = FakeClient()
    result = upload_dataset("sections", EXAMPLES, client=client, description="d")
    assert (result.created, result.added, result.present) == (True, 2, 2)
    assert result.name == "sections"
    assert client.datasets[0].metadata["content_sha256"] == content_digest(EXAMPLES)
    assert len(client.examples[client.datasets[0].id]) == 2


def test_a_second_upload_of_the_same_content_adds_nothing():
    client = FakeClient()
    first = upload_dataset("sections", EXAMPLES, client=client)
    writes = list(client.writes)
    second = upload_dataset("sections", EXAMPLES, client=client)
    assert (second.created, second.added, second.present) == (False, 0, 2)
    assert second.dataset_id == first.dataset_id
    assert client.writes == writes


def test_a_second_upload_of_different_content_is_refused_and_writes_nothing():
    client = FakeClient()
    upload_dataset("sections", EXAMPLES, client=client)
    writes = list(client.writes)
    changed = [dict(EXAMPLES[0], inputs={"x": 9}), EXAMPLES[1]]
    with pytest.raises(DatasetDiffersError, match="sections"):
        upload_dataset("sections", changed, client=client)
    assert client.writes == writes


def test_an_interrupted_upload_with_no_examples_is_completed_once():
    client = FakeClient()
    upload_dataset("sections", EXAMPLES, client=client)
    client.examples[client.datasets[0].id].clear()
    result = upload_dataset("sections", EXAMPLES, client=client)
    assert (result.created, result.added, result.present) == (False, 2, 2)


def test_a_partly_filled_dataset_is_refused():
    client = FakeClient()
    upload_dataset("sections", EXAMPLES, client=client)
    client.examples[client.datasets[0].id].pop()
    with pytest.raises(DatasetIncompleteError, match="1 of 2"):
        upload_dataset("sections", EXAMPLES, client=client)


def test_a_dataset_with_no_digest_on_record_is_refused():
    client = FakeClient()
    client.create_dataset("sections", metadata=None)
    with pytest.raises(DatasetDiffersError, match="no content digest"):
        upload_dataset("sections", EXAMPLES, client=client)


def test_two_datasets_with_one_name_are_refused():
    client = FakeClient()
    client.create_dataset("sections", metadata={})
    client.create_dataset("sections", metadata={})
    with pytest.raises(DatasetNameError, match="2 datasets"):
        upload_dataset("sections", EXAMPLES, client=client)


def test_an_empty_example_list_is_refused():
    with pytest.raises(ValueError, match="no examples"):
        upload_dataset("sections", [], client=FakeClient())


def test_a_dataset_whose_name_only_contains_the_wanted_one_is_not_taken_for_it():
    client = FakeClient()
    client.create_dataset("sections-old", metadata={"content_sha256": "x"})
    client.list_datasets = lambda **kw: iter(client.datasets)
    result = upload_dataset("sections", EXAMPLES, client=client)
    assert result.created is True
