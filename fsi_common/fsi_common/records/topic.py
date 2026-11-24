"""A topic's declaration for its facts: the closed list of kinds and the attributes copied word
for word from the source, which with the kind, subject and quote make a fact's identity."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic_core import PydanticCustomError

FACT_TOPIC_CONTEXT_KEY = "fsi_common.fact_topic"
"""Validation context key holding the topic's declaration for its facts (a ``FactTopic``)."""


@dataclass(frozen=True)
class FactTopic:
    """What a topic declares about its facts; ``fsi_common`` holds no list of its own.

    ``kinds`` is the closed list of fact kinds. ``copied_attributes`` names the attributes the
    topic copies word for word from the source (a deadline as written, for example); only these
    enter a fact's id beside its kind, subject and quote. Attributes a model words (a requirement
    in plain words, a summary) stay in the record and out of the id, so a rerun that words them
    differently finds the same fact.
    """

    kinds: frozenset[str]
    copied_attributes: frozenset[str]


def fact_topic_context(
    *, kinds: Iterable[str], copied_attributes: Iterable[str]
) -> dict[str, FactTopic]:
    """Return the validation context that holds a topic's declaration for its facts.

    Args:
        kinds: The topic's closed list of fact kinds.
        copied_attributes: The attributes the topic copies word for word from the source.

    Returns:
        A context to pass to ``Fact.build`` and ``Fact.model_validate``, which need it.
    """
    return {
        FACT_TOPIC_CONTEXT_KEY: FactTopic(
            kinds=frozenset(kinds), copied_attributes=frozenset(copied_attributes)
        )
    }


def fact_topic(context: Mapping[str, Any] | None, *, known: FactTopic | None = None) -> FactTopic:
    """Return the topic's declaration from a validation context.

    Args:
        context: The validation context.
        known: The declaration a fact was already validated with, used when the context holds
            none (a validated fact placed inside another record).

    Returns:
        The declaration.

    Raises:
        pydantic_core.PydanticCustomError: ``fact.kind``, if the context holds no declaration,
            because a fact's kind and id cannot be checked without it.
    """
    topic = (context or {}).get(FACT_TOPIC_CONTEXT_KEY, known)
    if not isinstance(topic, FactTopic):
        raise PydanticCustomError(
            "fact.kind",
            "no topic declaration of fact kinds and copied attributes was given, so the fact's "
            "kind and id cannot be checked; pass the topic's fact_topic_context",
        )
    return topic


def fact_id_basis(data: Mapping[str, Any], copied_attributes: Iterable[str]) -> dict[str, Any]:
    """Return what a fact's id is derived from, given the fact as JSON.

    Args:
        data: The fact's JSON, or its fields dumped as JSON.
        copied_attributes: The topic's attributes copied word for word from the source.

    Returns:
        The kind, the subject, the quote and the copied attributes the fact holds.
    """
    copied = set(copied_attributes)
    return {
        "kind": data["kind"],
        "subject": data["subject"],
        "quote": data["quote"],
        "attributes": {k: v for k, v in data["attributes"].items() if k in copied},
    }
