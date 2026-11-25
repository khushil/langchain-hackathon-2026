"""Probe topic folders for the shell's process tests: each has a ``utils`` package of its own."""

from __future__ import annotations

from pathlib import Path

# A topic folder with its own ``utils`` package, so two of them collide in one process. The page
# shows the value its own ``utils`` holds; the other routes let a test see what passes through.
PLUGIN_SOURCE = """
import asyncio
import sys
import time
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

from fsi_common.app import Answer, Tile, TopicPlugin, render
from utils import VALUE

HERE = Path(__file__).parent
if (HERE / "broken.flag").exists():
    raise ImportError("the probe was told to break")
if (HERE / "slow.flag").exists():
    time.sleep(120)
STATE = {"folder": "", "seeded": False}


async def index(request):
    answer = Answer(sentence="Value is " + VALUE + ".", tiles=(Tile(label="Things", value="2"),))
    return render(request, "probe/index.html", {"answer": answer, "page_title": "Probe"})


async def echo(request):
    form = dict(await request.form()) if request.method == "POST" else {}
    return JSONResponse(
        {
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query,
            "form": form,
            "cookie": request.headers.get("cookie", ""),
        }
    )


async def redirect(request):
    return RedirectResponse("@@PREFIX@@/echo?x=1", status_code=303)


async def csv(request):
    async def rows():
        for number in range(3):
            yield f"row,{number}\\r\\n"
            await asyncio.sleep(0.4)

    return StreamingResponse(
        rows(),
        media_type="text/csv",
        headers={"content-disposition": 'attachment; filename="probe.csv"'},
    )


async def cookies(request):
    response = Response("cookies")
    response.set_cookie("first", "1")
    response.set_cookie("second", "2")
    return response


async def gone(request):
    raise HTTPException(404, "There is no thing numbered 7.")


async def boom(request):
    raise RuntimeError("the probe broke")


async def syspath(request):
    return JSONResponse({"path": sys.path, "utils": VALUE})


async def state(request):
    return JSONResponse(STATE)


def use_state_dir(folder):
    STATE["folder"] = str(folder)
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / "marker.txt").write_text("@@NAME@@")


def seed():
    STATE["seeded"] = True


PLUGIN = TopicPlugin(
    name="@@NAME@@",
    title="@@TITLE@@",
    summary="The @@NAME@@ probe.",
    prefix="@@PREFIX@@",
    routes=[
        Route("/", index),
        Route("/echo", echo, methods=["GET", "POST"]),
        Route("/redirect", redirect),
        Route("/csv", csv),
        Route("/cookies", cookies),
        Route("/gone", gone),
        Route("/boom", boom),
        Route("/syspath", syspath),
        Route("/state", state),
    ],
    templates_dir=HERE / "templates",
    static_dir=HERE / "static",
    about=("About the @@NAME@@ probe.",),
    waiting=lambda: @@WAITING@@,
    waiting_noun="@@NOUN@@",
    seed=seed,
    use_state_dir=use_state_dir,
)
"""

# The topic's part of the offline edition: its application in one process, opening on its list.
OFFLINE_SOURCE = """
from fsi_common.app import AppConfig, create_app
from fsi_common.app.offline import OfflineTopic
from review_app.plugin import PLUGIN


def build_app():
    return create_app(AppConfig(secret=b"offline", topic_folders=()), topics=[PLUGIN])


HOOK = OfflineTopic(name="@@NAME@@", build_app=build_app, seed=lambda client: PLUGIN.list_href)
"""

TEMPLATE = """{% extends "base.html" %}
{% import "macros.html" as ui %}
{% block main %}
{{ ui.answer(answer) }}
<div class="exhibit" data-hook="exhibit"><p>Probe exhibit</p></div>
{% endblock %}
"""


def make_probe_topic(
    root: Path,
    folder: str,
    *,
    name: str,
    value: str,
    waiting: str = "0",
    noun: str = "case",
    prefix: str | None = None,
    title: str | None = None,
) -> Path:
    """Write a topic folder whose ``utils`` package holds ``value``, and return the folder."""
    path = root / folder
    (path / "utils").mkdir(parents=True)
    (path / "utils" / "__init__.py").write_text(f'VALUE = "{value}"\n')
    package = path / "review_app"
    (package / "templates" / "probe").mkdir(parents=True)
    (package / "static").mkdir()
    (package / "__init__.py").write_text('"""Probe."""\n')
    (package / "templates" / "probe" / "index.html").write_text(TEMPLATE)
    (package / "static" / "toy.css").write_text("body { margin: 0; }\n")
    source = PLUGIN_SOURCE
    for key, text in {
        "@@NAME@@": name,
        "@@TITLE@@": title or name.capitalize(),
        "@@PREFIX@@": prefix or f"/{name}",
        "@@WAITING@@": waiting,
        "@@NOUN@@": noun,
    }.items():
        source = source.replace(key, text)
    (package / "plugin.py").write_text(source)
    (package / "offline.py").write_text(OFFLINE_SOURCE.replace("@@NAME@@", name))
    return path


def make_broken_topic(root: Path, folder: str, *, hang_seconds: float = 0.0) -> Path:
    """Write a topic folder whose plug-in raises on import, or sleeps first when asked."""
    path = root / folder
    (path / "review_app").mkdir(parents=True)
    (path / "review_app" / "__init__.py").write_text('"""Broken."""\n')
    body = f"import time\ntime.sleep({hang_seconds})\n" if hang_seconds else ""
    (path / "review_app" / "plugin.py").write_text(body + 'raise ImportError("probe is broken")\n')
    return path


def two_probes(root: Path) -> tuple[Path, Path]:
    """Make the usual pair of probe topics: alpha waiting for one case and beta for none."""
    return (
        make_probe_topic(root, "01_alpha_agent", name="alpha", value="a", waiting="1"),
        make_probe_topic(root, "02_beta_agent", name="beta", value="b", waiting="0"),
    )
