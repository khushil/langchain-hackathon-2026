"""One topic's process: its own application on a loopback socket the shell handed over."""

from __future__ import annotations

import ctypes
import logging
import os
import signal
import socket
from dataclasses import replace

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fsi_common.app.app import create_app
from fsi_common.app.config import AppConfig, ConfigError
from fsi_common.app.home import WaitingCountError
from fsi_common.app.topic_info import TopicInfo
from fsi_common.app.topics import TopicPlugin, load_topic

log = logging.getLogger(__name__)

TOPIC_PATH = "/_shell/topic"
PR_SET_PDEATHSIG = 1


def die_with_parent(parent_pid: int) -> None:
    """Ask the system to end this process when the shell that started it ends.

    Args:
        parent_pid: The shell's process number.

    Raises:
        SystemExit: If the shell has already gone.
        OSError: If the system refuses the request.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, int(signal.SIGTERM), 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "The system refused to tie this process to the shell.")
    if os.getppid() != parent_pid:
        raise SystemExit("The shell that started this process has already ended.")


def topic_answer(plugin: TopicPlugin):
    """Make the handler that tells the shell about the topic and what waits in it.

    Args:
        plugin: The topic's plug-in.

    Returns:
        A handler answering with the topic's description and its waiting count as JSON.

    Raises:
        TopicInfoError: If the topic's prefix is not one path segment.
    """
    info = TopicInfo.from_plugin(plugin)

    def answer(request: Request) -> Response:
        waiting = plugin.waiting()
        if waiting is not None and waiting < 0:
            raise WaitingCountError(f"The waiting count of {plugin.title} cannot be below nought.")
        return JSONResponse({**info.to_dict(), "waiting": waiting})

    return answer


def create_topic_app(config: AppConfig) -> Starlette:
    """Build the application of the one topic this process serves.

    The topic's starting work is made only when ``APP_SEED`` lists this topic, because the shell
    gives the same setting to every topic's process; the application it builds is given this
    topic's name alone.

    Args:
        config: The settings; ``topic_folders`` holds the one topic's folder.

    Returns:
        The application, with the answer the shell asks for at ``/_shell/topic``.

    Raises:
        ConfigError: If the settings do not name exactly one topic folder.
        TopicLoadError: If the topic cannot be loaded.
        TopicInfoError: If the topic's prefix is not one path segment.
    """
    if len(config.topic_folders) != 1:
        raise ConfigError("A topic's process serves one topic; APP_TOPICS must name one folder.")
    plugin = load_topic(config.topic_folders[0])
    seed = plugin.name if plugin.name in config.seeds else ""
    app = create_app(
        replace(config, seed=seed),
        topics=[plugin],
        extra_routes=[Route(TOPIC_PATH, topic_answer(plugin))],
    )
    app.state.lists_peers = True
    return app


def main() -> None:
    """Serve the topic on the socket named by ``APP_LISTEN_FD``."""
    config = AppConfig.from_env()
    try:
        fd = int(os.environ["APP_LISTEN_FD"])
        parent = int(os.environ["APP_PARENT_PID"])
    except (KeyError, ValueError) as exc:
        raise ConfigError(
            "APP_LISTEN_FD and APP_PARENT_PID must be whole numbers; the shell sets both."
        ) from exc
    die_with_parent(parent)
    app = create_topic_app(config)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    server.run(sockets=[socket.socket(fileno=fd)])


if __name__ == "__main__":
    main()
