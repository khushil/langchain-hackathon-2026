"""What the shell knows of a topic without importing it, and the topic list a child draws."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fsi_common.app.topics import TopicPlugin

log = logging.getLogger(__name__)

PEERS_HEADER = "x-review-desk-topics"
PREFIX_PATTERN = re.compile(r"/[A-Za-z0-9_-]+")


class TopicInfoError(ValueError):
    """A topic's description is missing a field or holds one the shell cannot use."""


@dataclass(frozen=True)
class TopicInfo:
    """A topic as the shell's pages need it: its words and its address, with no code behind it.

    The shell routes a request by the first segment of its path, so a topic's prefix is one
    segment such as ``/brief``.
    """

    name: str
    title: str
    prefix: str
    summary: str = ""
    about: tuple[str, ...] = ()
    waiting_noun: str = "item"

    def __post_init__(self) -> None:
        if not PREFIX_PATTERN.fullmatch(self.prefix):
            raise TopicInfoError(
                f"The prefix '{self.prefix}' of the topic '{self.name}' must be one path segment "
                "of letters, digits, hyphens and underscores, such as '/brief'."
            )

    @property
    def list_href(self) -> str:
        """The address of the topic's list page."""
        return f"{self.prefix}/"

    @classmethod
    def from_plugin(cls, plugin: TopicPlugin) -> TopicInfo:
        """Describe a loaded plug-in.

        Args:
            plugin: The topic's plug-in.

        Returns:
            Its words and address.

        Raises:
            TopicInfoError: If its prefix is not one path segment.
        """
        return cls(
            name=plugin.name,
            title=plugin.title,
            prefix=plugin.prefix,
            summary=plugin.summary,
            about=tuple(plugin.about),
            waiting_noun=plugin.waiting_noun,
        )

    def to_dict(self) -> dict:
        """Return the description as plain data for the child's answer."""
        return {
            "name": self.name,
            "title": self.title,
            "prefix": self.prefix,
            "summary": self.summary,
            "about": list(self.about),
            "waiting_noun": self.waiting_noun,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> TopicInfo:
        """Read a description a child sent.

        Args:
            data: The child's answer.

        Returns:
            The description.

        Raises:
            TopicInfoError: If a field is missing or has the wrong kind of value.
        """
        try:
            return cls(
                name=str(data["name"]),
                title=str(data["title"]),
                prefix=str(data["prefix"]),
                summary=str(data.get("summary", "")),
                about=tuple(str(p) for p in data.get("about", ())),
                waiting_noun=str(data.get("waiting_noun", "item")),
            )
        except (KeyError, TypeError) as exc:
            raise TopicInfoError(f"A topic's description is incomplete: {exc!r}.") from exc


def title_from_folder(folder: Path) -> str:
    """Make a topic's title from its folder's name, for a topic that never said its own.

    Args:
        folder: The topic folder, such as ``02_transaction_monitoring_agent``.

    Returns:
        The name without its number and ``_agent`` ending, in words: ``Transaction monitoring``.
    """
    words = re.sub(r"^\d+_", "", folder.name)
    words = re.sub(r"_agent$", "", words).replace("_", " ").strip() or folder.name
    return words[:1].upper() + words[1:]


def encode_peers(topics: Sequence[TopicInfo]) -> str:
    """Write the topics' names, titles and prefixes as the ASCII text of the topic list header."""
    return json.dumps(
        [{"name": t.name, "title": t.title, "prefix": t.prefix} for t in topics],
        separators=(",", ":"),
    )


def decode_peers(value: str | None) -> tuple[TopicInfo, ...]:
    """Read the topic list header.

    Args:
        value: The header's text, or None when the request had none.

    Returns:
        The topics, or none when the header is absent or is not a list of topics with usable
        prefixes; a header that is wrong is logged and the page draws its own topic alone.
    """
    if not value:
        return ()
    try:
        return tuple(TopicInfo.from_dict(item) for item in json.loads(value))
    except (ValueError, TypeError, AttributeError) as exc:
        log.warning("The topic list header was not usable and is ignored: %s", exc)
        return ()
