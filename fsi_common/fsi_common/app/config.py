"""Settings of the reviewer's application, read from the environment."""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 4803
COOKIE_PREFIX = "reviewer"
COOKIE_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class ConfigError(ValueError):
    """A setting of the application has a value it cannot use."""


@dataclass(frozen=True)
class AppConfig:
    """Where the application listens, what signs its sessions and which topics it serves."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    secret: bytes = field(default_factory=lambda: secrets.token_bytes(32), repr=False)
    topic_folders: tuple[Path, ...] = ()
    cookie: str = ""
    seed: str = ""

    @property
    def cookie_name(self) -> str:
        """The name of the sign-in cookie: ``cookie`` when set, else one made from the port.

        A browser keeps cookies by host and not by port, so two applications on two ports of one
        host would otherwise replace each other's sign-in.
        """
        return self.cookie or f"{COOKIE_PREFIX}-{self.port}"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AppConfig:
        """Read the settings.

        ``APP_HOST`` and ``APP_PORT`` say where to listen, ``APP_SECRET`` signs sessions (a random
        one is made for each process when it is absent), ``APP_COOKIE`` names the sign-in cookie
        (``reviewer-`` and the port when it is absent), and ``APP_TOPICS`` lists topic folders
        separated as a path is. Without it every topic folder of the repository that holds a
        ``review_app/plugin.py`` is served. ``APP_SEED`` names a topic whose starting work is made
        when the application starts; without it the application starts empty.

        Args:
            environ: The environment to read; the process's own when absent.

        Returns:
            The settings.

        Raises:
            ConfigError: If the port is not a whole number from 1 to 65535, or ``APP_COOKIE`` is
                not a name of letters, digits, hyphens and underscores.
        """
        env = os.environ if environ is None else environ
        raw_port = env.get("APP_PORT", str(DEFAULT_PORT))
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise ConfigError(f"APP_PORT is '{raw_port}', which is not a whole number.") from exc
        if not 1 <= port <= 65535:
            raise ConfigError(f"APP_PORT is {port}; use a port from 1 to 65535.")
        cookie = env.get("APP_COOKIE", "")
        if "APP_COOKIE" in env and not COOKIE_NAME_PATTERN.fullmatch(cookie):
            raise ConfigError(
                "APP_COOKIE must be 1 to 64 letters, digits, hyphens or underscores; "
                f"it is '{cookie}'."
            )
        secret = env.get("APP_SECRET")
        listed = env.get("APP_TOPICS")
        folders = (
            tuple(Path(item) for item in listed.split(os.pathsep) if item.strip())
            if listed is not None
            else built_topic_folders(REPOSITORY_ROOT)
        )
        return cls(
            host=env.get("APP_HOST", DEFAULT_HOST),
            port=port,
            secret=secret.encode("utf-8") if secret else secrets.token_bytes(32),
            topic_folders=folders,
            cookie=cookie,
            seed=env.get("APP_SEED", "").strip(),
        )


def built_topic_folders(root: Path) -> tuple[Path, ...]:
    """Return the topic folders under a repository root that have a plug-in for the application.

    Args:
        root: The repository root.

    Returns:
        Each folder holding ``review_app/plugin.py``, in name order.
    """
    return tuple(
        sorted(path.parent.parent for path in root.glob("*/review_app/plugin.py") if path.is_file())
    )
