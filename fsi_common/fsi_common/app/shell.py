"""The shell: one address for every topic, with each topic in a process of its own.

The shell serves the home page, About, sign-in and the shared files itself. It starts one
process for each topic folder, holding only that folder and this package on its path, and passes
every request under a topic's address to that topic's process. Topics keep the starter's package
names (each has a ``utils``), which cannot share one process.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from fsi_common.app.app import STATIC_DIR, http_error, sign_in, sign_in_form, sign_out
from fsi_common.app.children import (
    ChildStartError,
    TopicChild,
    check_state_layout,
    make_children,
    shared_secret,
    stop_children,
)
from fsi_common.app.config import AppConfig
from fsi_common.app.proxy import is_gone, make_client
from fsi_common.app.rendering import make_environment
from fsi_common.app.session import SessionCodec
from fsi_common.app.shell_pages import about_page, forward, home
from fsi_common.app.topic_info import TopicInfo, TopicInfoError
from fsi_common.app.topics import NoTopicsError, TopicLoadError, check_distinct, seed_name_error

log = logging.getLogger(__name__)

ASK_SECONDS = 3.0
RESTART_GAP_SECONDS = 60.0
SETTLE_SECONDS = 1.0
SETTLE_STEP = 0.05
POLL_SECONDS = 0.2
METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


class ChildAnswerError(RuntimeError):
    """A topic's process did not give the shell the answer it asked for.

    ``gone`` is true when the connection was refused or reset, which a process that has ended
    gives, and false for a timeout, which a frozen process gives.
    """

    def __init__(self, message: str, *, gone: bool = False) -> None:
        super().__init__(message)
        self.gone = gone


class TopicList:
    """The topics that have said who they are, in the order their folders were given."""

    def __init__(self, children: Sequence[TopicChild]) -> None:
        self._children = children

    def __iter__(self) -> Iterator[TopicInfo]:
        return iter([c.info for c in self._children if c.info is not None])

    def __len__(self) -> int:
        return sum(c.info is not None for c in self._children)


async def ask_child(client: httpx.AsyncClient, child: TopicChild) -> None:
    """Ask a topic's process who it is and what waits in it, and keep the answer.

    Args:
        client: The client for topics' processes.
        child: The topic's process.

    Raises:
        ChildAnswerError: If the process is not running, does not answer, or answers wrongly.
    """
    if not child.running():
        raise ChildAnswerError(f"The process for {child.folder} is not running.")
    try:
        answer = await client.get(f"{child.base_url}/_shell/topic", timeout=ASK_SECONDS)
        answer.raise_for_status()
        data = answer.json()
        info, waiting = TopicInfo.from_dict(data), data.get("waiting")
    except (httpx.HTTPError, ValueError, AttributeError, TopicInfoError) as exc:
        raise ChildAnswerError(
            f"The process for {child.folder} gave no usable answer.", gone=is_gone(exc)
        ) from exc
    child.info, child.waiting = info, waiting
    child.answering = True


class Shell:
    """The processes of every topic and what the shell has learned from them."""

    def __init__(self, config: AppConfig, folders: Sequence[Path]) -> None:
        self.config = config
        self.children = make_children(config, folders)
        self.client = make_client()
        self.topics = TopicList(self.children)
        self.restart_gap = RESTART_GAP_SECONDS

    async def start(self) -> None:
        """Start every topic's process and wait until each has answered or the time is up.

        Raises:
            SeedError: If ``APP_SEED`` names a topic that did not answer.
        """
        # Not in a pool thread: a process is tied to the thread that started it, and a pool
        # thread may end. Popen returns at once, so starting here does not hold the loop.
        self._start_all()
        await asyncio.gather(*(self._wait_for(c) for c in self.children))
        silent = [c for c in self.children if c.info is None]
        for child in silent:
            log.error(
                "The topic in %s did not answer, so it is shown as not reached.", child.folder
            )
        answered = [c.info for c in self.children if c.info is not None]
        if answered:
            check_distinct(answered)
        self._check_seed(len(silent))

    def _start_all(self) -> None:
        for child in self.children:
            try:
                child.start(self.config)
            except ChildStartError:
                log.exception("A topic's process could not be started.")

    async def _wait_for(self, child: TopicChild) -> None:
        deadline = time.monotonic() + self.config.child_start_seconds
        while child.running() and time.monotonic() < deadline:
            try:
                await ask_child(self.client, child)
            except ChildAnswerError:
                await asyncio.sleep(POLL_SECONDS)
            else:
                return

    def _check_seed(self, not_started: int) -> None:
        names = [c.info.name for c in self.children if c.info is not None]
        unknown = [name for name in self.config.seeds if name not in names]
        if unknown:
            raise seed_name_error(unknown, names, not_started=not_started)

    async def stop(self) -> None:
        """Stop every process this shell started and close its client."""
        tasks = [c.restart_task for c in self.children if c.restart_task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.client.aclose()
        await asyncio.to_thread(stop_children, self.children)

    async def ensure_info(self) -> None:
        """Ask again each running topic that has not yet said who it is."""
        missing = [c for c in self.children if c.info is None and c.running()]
        await asyncio.gather(*(self.try_ask(c) for c in missing))

    async def try_ask(self, child: TopicChild) -> bool:
        """Ask a topic's process about itself and say whether it answered.

        Args:
            child: The topic's process.

        Returns:
            True when it answered and its description and count were kept; False, with the reason
            logged, when it did not.
        """
        if self.restarting(child):
            return False
        try:
            await ask_child(self.client, child)
        except ChildAnswerError as exc:
            log.warning("The topic in %s could not be reached.", child.folder, exc_info=True)
            if exc.gone:
                await self.after_gone(child)
            return False
        return True

    async def after_gone(self, child: TopicChild) -> str:
        """Check a topic's process after a refused or reset connection, and start it if it ended.

        A process that has just been killed is still counted as running for a few milliseconds,
        so the check waits up to ``SETTLE_SECONDS`` for it to be collected; a frozen process is
        still running after that and is left alone.

        Args:
            child: The topic's process.

        Returns:
            What ``revive`` says.
        """
        deadline = time.monotonic() + SETTLE_SECONDS
        while child.running() and time.monotonic() < deadline:
            await asyncio.sleep(SETTLE_STEP)
        return self.revive(child)

    def restarting(self, child: TopicChild) -> bool:
        """Say whether a topic's process was started again and has not yet answered."""
        return child.restart_task is not None and not child.restart_task.done()

    def revive(self, child: TopicChild) -> str:
        """Start a topic's process again if it has ended, at most once a minute for each topic.

        Called when a request needs the topic. A topic that never answered is not started again,
        because there is nothing to say it will do better.

        Args:
            child: The topic's process.

        Returns:
            ``"running"`` when the process runs; ``"starting"`` when it was just started again or
            is still starting; ``"waiting"`` when it has ended and was started again less than a
            minute ago; ``"unavailable"`` when it never answered or could not be started.
        """
        if self.restarting(child):
            return "starting"
        if child.running():
            return "running"
        now = time.monotonic()
        recent = child.restarted_at is not None and now - child.restarted_at < self.restart_gap
        if child.info is None:
            return "unavailable"
        if recent:
            return "waiting"
        child.restarted_at = now
        log.warning("The process for %s ended; starting it again.", child.folder)
        try:
            child.start(self.config)
        except ChildStartError:
            log.exception("The topic in %s could not be started again.", child.folder)
            return "unavailable"
        child.restart_task = asyncio.create_task(self._wait_for(child))
        child.restart_task.add_done_callback(lambda _: self._after_restart(child))
        return "starting"

    def _after_restart(self, child: TopicChild) -> None:
        if child.restart_task is not None and child.restart_task.cancelled():
            return
        if child.answering:
            log.warning("The topic in %s answers again.", child.folder)
        else:
            log.error("The topic in %s did not answer after it was started again.", child.folder)

    def child_at(self, prefix: str) -> TopicChild | None:
        """Return the topic that has said it serves ``prefix``, or None."""
        return next((c for c in self.children if c.info and c.info.prefix == prefix), None)


def create_shell(
    config: AppConfig | None = None, *, folders: Sequence[Path] | None = None
) -> Starlette:
    """Build the application that serves every topic, each in a process of its own.

    The processes start when the application starts and stop when it stops.

    Args:
        config: The settings; the environment's when absent.
        folders: The topic folders; those of the settings when absent.

    Returns:
        The application.

    Raises:
        NoTopicsError: If there is no topic folder.
        TopicLoadError: If a folder has no plug-in, or two folders share a name.
        StateLayoutError: If the state folder holds the files of a one-topic start.
    """
    config = config or AppConfig.from_env()
    chosen = list(folders if folders is not None else config.topic_folders)
    if not chosen:
        raise NoTopicsError(
            "No topic is configured. Set APP_TOPICS to topic folders that hold "
            "review_app/plugin.py, or build a topic with a plug-in."
        )
    for folder in chosen:
        if not (folder / "review_app" / "plugin.py").is_file():
            raise TopicLoadError(f"{folder} has no review_app/plugin.py, so it cannot be served.")
    names = [f.resolve().name for f in chosen]
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        raise TopicLoadError(f"Two topic folders share the name {', '.join(repeated)}.")
    check_state_layout(config.state_dir, chosen)
    shell = Shell(config, chosen)

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        try:
            await shell.start()
            yield
        finally:
            await shell.stop()

    app = Starlette(
        routes=[
            Route("/", home),
            Route("/about", about_page),
            Route("/signin", sign_in_form, methods=["GET"]),
            Route("/signin", sign_in, methods=["POST"]),
            Route("/signout", sign_out, methods=["POST"]),
            Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
            Route("/{path:path}", forward, methods=METHODS),
        ],
        exception_handlers={HTTPException: http_error},
        lifespan=lifespan,
    )
    app.state.config = config
    app.state.shell = shell
    app.state.topics = shell.topics
    app.state.sessions = SessionCodec(shared_secret(config).encode("ascii"))
    app.state.cookie_name = config.cookie_name
    app.state.templates = make_environment([])
    return app
