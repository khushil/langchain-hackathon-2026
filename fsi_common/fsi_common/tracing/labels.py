"""The metadata and tags every traced run carries, so LangSmith can filter and group by them.

The labels name the topic, the institution, the document and the review a run belongs to. They
travel beside a model request, in the run's configuration and on the model object, and never in
the request itself, so the key a recording is saved and found under does not depend on them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


class UnknownTopicError(Exception):
    """A label was asked for under a topic the repository does not have."""


@dataclass(frozen=True)
class Topic:
    """One of the repository's topics, as LangSmith names it."""

    key: str
    number: str
    name: str

    @property
    def label(self) -> str:
        """The topic's number and name, which is what the ``topic`` metadata key holds."""
        return f"{self.number}-{self.name}"


TOPICS: dict[str, Topic] = {
    "kyc": Topic("kyc", "01", "kyc-onboarding"),
    "monitoring": Topic("monitoring", "02", "transaction-monitoring"),
    "brief": Topic("brief", "03", "compliance-brief"),
}
"""Every topic by its short key; the number is the starter's folder number."""

INSTITUTION_KEYS = ("institution", "firm_id")
"""The keys that name the institution a run is for, first match wins."""
DOCUMENT_KEY = "document_id"
STAGE_REVIEW_TAG = "stage:review"


@dataclass(frozen=True)
class Labels:
    """The metadata and the tags for one run or one model."""

    metadata: dict[str, Any]
    tags: list[str] = field(default_factory=list)


def _topic(key: str) -> Topic:
    try:
        return TOPICS[key]
    except KeyError:
        raise UnknownTopicError(
            f"There is no topic '{key}'. The topics are: {', '.join(TOPICS)}."
        ) from None


def run_labels(topic: str, thread_id: str, metadata: Mapping[str, Any]) -> Labels:
    """Return the labels of a review's run: its topic, institution, document and thread.

    The result is stable: labelling the metadata it returned gives the same metadata and tags, so
    a run read back from the registry carries what it carried when it started.

    Args:
        topic: The topic's short key: ``kyc``, ``monitoring`` or ``brief``.
        thread_id: The review's thread id; every run of the review shares it, which is what
            LangSmith groups into one thread.
        metadata: What the topic already records about the run, such as its document and firm.

    Returns:
        The metadata (the given keys, plus the labels) and the tags.

    Raises:
        UnknownTopicError: If the topic is not one of the repository's.
    """
    chosen = _topic(topic)
    merged: dict[str, Any] = dict(metadata)
    merged["topic"] = chosen.label
    merged["topic_number"] = chosen.number
    merged["thread_id"] = thread_id
    merged["review_id"] = thread_id
    institution = next((merged[k] for k in INSTITUTION_KEYS if merged.get(k)), None)
    if institution is not None:
        merged["institution"] = institution
    tags = [f"topic:{chosen.label}"]
    if institution is not None:
        tags.append(f"institution:{institution}")
    if merged.get(DOCUMENT_KEY):
        tags.append(f"document:{merged[DOCUMENT_KEY]}")
    return Labels(metadata=merged, tags=tags)


def resume_tags(tags: list[str]) -> list[str]:
    """Return a run's tags with the mark of a review step, for the run resumed after a decision.

    Args:
        tags: The tags the review started with.

    Returns:
        The same tags, and ``stage:review`` once.
    """
    return list(tags) if STAGE_REVIEW_TAG in tags else [*tags, STAGE_REVIEW_TAG]


def model_labels(topic: str, role: str, *, model: str, effort: str | None) -> Labels:
    """Return the labels of one model: its topic and role, and the model and effort it runs on.

    Args:
        topic: The topic's short key.
        role: The role the model is chosen for, such as ``section`` or ``memo``.
        model: The model's name.
        effort: The effort, or None when the model's default is used.

    Returns:
        The metadata and the tags.

    Raises:
        UnknownTopicError: If the topic is not one of the repository's.
    """
    chosen = _topic(topic)
    metadata: dict[str, Any] = {
        "topic": chosen.label,
        "topic_number": chosen.number,
        "model_role": role,
        "model_name": model,
    }
    if effort is not None:
        metadata["model_effort"] = effort
    return Labels(metadata=metadata, tags=[f"topic:{chosen.label}", f"role:{role}"])
