"""The shell's own pages and the passing of a request to a topic's process."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from fsi_common.app.app import about
from fsi_common.app.children import TopicChild
from fsi_common.app.home import HomeEntry, HomeSummary, WaitingCountError
from fsi_common.app.proxy import ChildGoneError, ChildUnreachableError, pass_request
from fsi_common.app.rendering import render

if TYPE_CHECKING:
    from fsi_common.app.shell import Shell

log = logging.getLogger(__name__)


def _shell(request: Request) -> Shell:
    return request.app.state.shell


async def home(request: Request) -> Response:
    """Say what waits for a reviewer across the topics, asking each topic's process."""
    shell = _shell(request)
    for child in shell.children:
        shell.revive(child)
    reached = await asyncio.gather(*(shell.try_ask(c) for c in shell.children))
    entries = []
    for child, ok in zip(shell.children, reached, strict=True):
        count = child.waiting if ok else None
        if count is not None and count < 0:
            raise WaitingCountError(f"The waiting count of {child.title} cannot be below nought.")
        info = child.info
        entries.append(
            HomeEntry(
                child.title,
                info.list_href if info else None,
                info.waiting_noun if info else "item",
                count,
                reachable=ok,
                starting=shell.restarting(child),
            )
        )
    answer = HomeSummary(tuple(entries)).answer()
    return render(request, "home.html", {"answer": answer, "page_title": "Home"})


async def about_page(request: Request) -> Response:
    """Say what the data is, with each topic's paragraphs, asking those that have not yet said."""
    await _shell(request).ensure_info()
    return await about(request)


def has_dot_segment(path: str) -> bool:
    """Say whether a path has a segment of ``.`` or ``..``.

    The address the shell sends on is rebuilt by its client, which removes such segments, so a
    path the shell routed by its first segment could reach another route of the topic's process.
    The server has already read the percent signs of the path it gives, so none are read here.

    Args:
        path: The request's path as the server decoded it.

    Returns:
        True when any segment is a dot segment.
    """
    return any(segment in {".", ".."} for segment in path.split("/"))


async def forward(request: Request) -> Response:
    """Pass a request under a topic's address to that topic's process."""
    shell = _shell(request)
    if has_dot_segment(request.url.path):
        raise HTTPException(404)
    prefix = "/" + request.url.path.split("/")[1]
    child = shell.child_at(prefix)
    if child is None and any(c.info is None for c in shell.children):
        await shell.ensure_info()
        child = shell.child_at(prefix)
    if child is None:
        raise HTTPException(404)
    state = shell.revive(child)
    if state == "running" and not child.answering:
        if not await shell.try_ask(child):
            raise HTTPException(
                503, f"{child.title} could not be reached. It is running but did not answer."
            )
    elif state != "running":
        raise refusal(child, state)
    try:
        return await pass_request(
            shell.client, request, base_url=child.base_url, topics=list(shell.topics)
        )
    except ChildGoneError as exc:
        log.warning("The topic %s refused the request.", child.title, exc_info=True)
        state = await shell.after_gone(child)
        raise refusal(child, state) from exc
    except ChildUnreachableError as exc:
        log.warning("The topic %s could not be reached.", child.title, exc_info=True)
        raise refusal(child, "unavailable") from exc


def refusal(child: TopicChild, state: str) -> HTTPException:
    """Say in words why a topic's address cannot be served now.

    Args:
        child: The topic's process.
        state: What ``Shell.revive`` said: ``starting``, ``waiting``, ``running`` or
            ``unavailable``.

    Returns:
        The 503 to raise.
    """
    if state == "starting":
        detail = f"{child.title} stopped and is starting again. Reload this page in a few seconds."
    elif state == "waiting":
        detail = f"{child.title} could not be reached. It was started again less than a minute ago."
    else:
        detail = f"{child.title} could not be reached."
    return HTTPException(503, detail)
