"""A small topic for the shell's tests: a folder with a plug-in, one page and one static file."""

from __future__ import annotations

from pathlib import Path

PLUGIN_SOURCE = """
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.routing import Route

from fsi_common.app import Answer, Tile, TopicPlugin, render

HERE = Path(__file__).parent


async def index(request):
    tiles = (Tile(label="Things", value="2"),)
    answer = Answer(sentence="The toy topic has 2 things.", tiles=tiles)
    return render(request, "toy/index.html", {"answer": answer, "page_title": "Toy"})


async def gone(request):
    raise HTTPException(404, "There is no thing numbered 7.")


PLUGIN = TopicPlugin(
    name="toy",
    title="Toy topic",
    summary="A topic made for a test.",
    prefix="/toy",
    routes=[Route("/", index), Route("/gone", gone)],
    templates_dir=HERE / "templates",
    static_dir=HERE / "static",
    about=("The toy topic holds invented things.",),
)
"""

TEMPLATE = """{% extends "base.html" %}
{% import "macros.html" as ui %}
{% block main %}
{{ ui.answer(answer) }}
<div class="exhibit" data-hook="exhibit"><p>Toy exhibit</p></div>
{% endblock %}
"""


def make_toy_folder(root: Path, name: str = "toy_topic") -> Path:
    """Write a topic folder holding a plug-in for ``name`` under ``root`` and return it."""
    folder = root / name
    (folder / "review_app" / "templates" / "toy").mkdir(parents=True)
    (folder / "review_app" / "static").mkdir()
    (folder / "review_app" / "__init__.py").write_text('"""Toy."""\n')
    (folder / "review_app" / "plugin.py").write_text(PLUGIN_SOURCE)
    (folder / "review_app" / "templates" / "toy" / "index.html").write_text(TEMPLATE)
    (folder / "review_app" / "static" / "toy.css").write_text("body { margin: 0; }\n")
    return folder
