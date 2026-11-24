"""The topics the application serves, each found by importing its plug-in."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from starlette.routing import BaseRoute

PLUGIN_MODULE = "review_app.plugin"


class NoTopicsError(RuntimeError):
    """The application was asked to start with no topic to serve."""


class TopicLoadError(RuntimeError):
    """A topic's plug-in could not be loaded; the message names the folder and the cause."""


@dataclass(frozen=True)
class TopicPlugin:
    """What a topic gives the application: its name, address, routes and templates.

    ``about`` holds the paragraphs About shows for the topic: what its data is and how its output
    is made. The shell itself names no document.

    Templates sit in a folder named for the topic inside ``templates_dir``, so topics' file names
    never meet. A topic's pages extend ``base.html`` and are rendered with ``render``.
    """

    name: str
    title: str
    summary: str
    prefix: str
    routes: Sequence[BaseRoute]
    templates_dir: Path
    static_dir: Path | None = None
    about: Sequence[str] = ()
    template_globals: Mapping[str, Callable] = field(default_factory=dict)
    template_filters: Mapping[str, Callable] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.prefix.startswith("/") or self.prefix.endswith("/") or len(self.prefix) < 2:
            raise ValueError(f"The prefix '{self.prefix}' must be a path such as '/brief'.")


def _own_copy(folder: Path) -> bool:
    module = sys.modules.get("review_app")
    path = getattr(module, "__file__", None)
    return path is not None and Path(path).resolve().parent == (folder / "review_app").resolve()


def load_topic(folder: Path) -> TopicPlugin:
    """Import one topic folder's ``review_app.plugin`` and return its ``PLUGIN``.

    Topics share the package name ``review_app``, so a topic other than the one already imported
    is loaded with its own copy of the package and the copy is dropped afterwards.

    Args:
        folder: The topic folder.

    Returns:
        The topic's plug-in.

    Raises:
        TopicLoadError: If the folder has no plug-in, importing it fails, or it exports no PLUGIN.
    """
    folder = folder.resolve()
    if not (folder / "review_app" / "plugin.py").is_file():
        raise TopicLoadError(f"{folder} has no review_app/plugin.py, so it cannot be served.")
    shared = _own_copy(folder)
    held = {} if shared else _take_package()
    sys.path.insert(0, str(folder))
    try:
        module = importlib.import_module(PLUGIN_MODULE)
    except (ImportError, SyntaxError) as exc:
        raise TopicLoadError(f"The plug-in in {folder} could not be imported: {exc}") from exc
    finally:
        sys.path.remove(str(folder))
        if not shared:
            _take_package()
            sys.modules.update(held)
    plugin = getattr(module, "PLUGIN", None)
    if not isinstance(plugin, TopicPlugin):
        raise TopicLoadError(f"{folder}/review_app/plugin.py exports no PLUGIN of the right type.")
    return plugin


def _take_package() -> dict[str, object]:
    names = [n for n in sys.modules if n == "review_app" or n.startswith("review_app.")]
    return {name: sys.modules.pop(name) for name in names}


def load_topics(folders: Sequence[Path]) -> list[TopicPlugin]:
    """Load every configured topic.

    Args:
        folders: The topic folders.

    Returns:
        The plug-ins, in the order given.

    Raises:
        NoTopicsError: If there are no folders.
        TopicLoadError: If one cannot be loaded, or two share a name or an address.
    """
    if not folders:
        raise NoTopicsError(
            "No topic is configured. Set APP_TOPICS to topic folders that hold "
            "review_app/plugin.py, or build a topic with a plug-in."
        )
    plugins = [load_topic(folder) for folder in folders]
    check_distinct(plugins)
    return plugins


def check_distinct(plugins: Sequence[TopicPlugin]) -> None:
    """Refuse two topics that share a name or an address.

    Args:
        plugins: The topics.

    Raises:
        NoTopicsError: If there are none.
        TopicLoadError: If two share a name or a prefix.
    """
    if not plugins:
        raise NoTopicsError("The application has no topic to serve.")
    for attribute in ("name", "prefix"):
        values = [getattr(p, attribute) for p in plugins]
        repeated = sorted({v for v in values if values.count(v) > 1})
        if repeated:
            raise TopicLoadError(f"Two topics share the {attribute} {', '.join(repeated)}.")
