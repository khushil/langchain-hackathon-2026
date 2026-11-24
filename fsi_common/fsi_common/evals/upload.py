"""Upload a dataset of reference examples to LangSmith once, and refuse to change it on a rerun."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

DIGEST_KEY = "content_sha256"


class UploadError(Exception):
    """A dataset could not be uploaded."""


class DatasetDiffersError(UploadError):
    """A dataset with the name exists and holds different content from the one offered."""


class DatasetIncompleteError(UploadError):
    """A dataset with the name and the right content holds only some of its examples."""


class DatasetNameError(UploadError):
    """More than one dataset has the name, so none can be chosen."""


class DatasetClient(Protocol):
    """The parts of the LangSmith client the upload uses."""

    def list_datasets(self, *, dataset_name: str | None = None, **kwargs: Any) -> Any:
        """Datasets, optionally those with a given name."""

    def create_dataset(self, dataset_name: str, **kwargs: Any) -> Any:
        """Make a dataset and return it."""

    def create_examples(self, *, dataset_id: Any, examples: Sequence[dict], **kwargs: Any) -> Any:
        """Add examples to a dataset."""

    def list_examples(self, *, dataset_id: Any, **kwargs: Any) -> Any:
        """The examples of a dataset."""


@dataclass(frozen=True)
class UploadResult:
    """What an upload did: the dataset, whether it was created, and how many examples it added."""

    name: str
    dataset_id: str
    created: bool
    added: int
    present: int


def to_langsmith_examples(examples: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Map reference examples to LangSmith's shape.

    An example has `key`, `inputs`, `reference_outputs` and `metadata`.

    Args:
        examples: The examples as the topic builds them.

    Returns:
        Dicts with `inputs`, `outputs` and `metadata`, the key kept in the metadata.
    """
    return [
        {
            "inputs": example["inputs"],
            "outputs": example["reference_outputs"],
            "metadata": {**example.get("metadata", {}), "key": example["key"]},
        }
        for example in examples
    ]


def content_digest(examples: Sequence[Mapping[str, Any]]) -> str:
    """The SHA-256 of the examples' canonical JSON, independent of key order.

    Args:
        examples: The examples as the topic builds them.

    Returns:
        The digest in lower-case hex.
    """
    canonical = json.dumps(
        to_langsmith_examples(examples), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def upload_dataset(
    name: str,
    examples: Sequence[Mapping[str, Any]],
    *,
    client: DatasetClient,
    description: str | None = None,
) -> UploadResult:
    """Create the named dataset with its examples, or confirm it already holds the same examples.

    The dataset's metadata keeps the content digest. On a rerun the digest decides: a match adds
    nothing, and a difference is refused, so the dataset an experiment ran against is never altered.

    Args:
        name: The dataset's name.
        examples: The examples, as the topic builds them.
        client: A LangSmith client, or a fake with the same methods.
        description: Text for the dataset on creation.

    Returns:
        What the upload did.

    Raises:
        ValueError: If there are no examples.
        DatasetNameError: If more than one dataset has the name.
        DatasetDiffersError: If the dataset exists with another digest, or with none.
        DatasetIncompleteError: If the dataset holds some but not all of the examples.
    """
    if not examples:
        raise ValueError("no examples to upload")
    digest = content_digest(examples)
    payload = to_langsmith_examples(examples)
    found = [d for d in client.list_datasets(dataset_name=name) if d.name == name]
    if len(found) > 1:
        raise DatasetNameError(f"{len(found)} datasets are named {name}; remove the extras by hand")
    if not found:
        dataset = client.create_dataset(
            name,
            description=description,
            metadata={DIGEST_KEY: digest, "example_count": len(payload)},
        )
        client.create_examples(dataset_id=dataset.id, examples=payload)
        return UploadResult(name, str(dataset.id), True, len(payload), len(payload))
    dataset = found[0]
    recorded = (dataset.metadata or {}).get(DIGEST_KEY)
    if recorded is None:
        raise DatasetDiffersError(
            f"dataset {name} has no content digest on record, so it is not changed"
        )
    if recorded != digest:
        raise DatasetDiffersError(
            f"dataset {name} holds different content "
            f"(digest {recorded[:12]}, offered {digest[:12]}); "
            "give the new content a new name"
        )
    present = sum(1 for _ in client.list_examples(dataset_id=dataset.id))
    if present == len(payload):
        return UploadResult(name, str(dataset.id), False, 0, present)
    if present == 0:
        client.create_examples(dataset_id=dataset.id, examples=payload)
        return UploadResult(name, str(dataset.id), False, len(payload), len(payload))
    raise DatasetIncompleteError(f"dataset {name} holds {present} of {len(payload)} examples")
