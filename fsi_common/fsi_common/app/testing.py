"""Helpers for tests that need the application served for a real browser."""

from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette

STARTUP_SECONDS = 10.0


class ServerStartError(RuntimeError):
    """The test server did not start listening in time."""


@dataclass
class RunningServer:
    """An application served on the loopback address, stopped through its own handle."""

    base_url: str
    server: uvicorn.Server
    thread: threading.Thread

    def stop(self) -> None:
        """Ask the server to finish and wait for its thread."""
        self.server.should_exit = True
        self.thread.join(timeout=STARTUP_SECONDS)


def free_port() -> int:
    """Return a port on 127.0.0.1 that nothing is listening on now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def serve(app: Starlette) -> RunningServer:
    """Serve an application on 127.0.0.1 at a port chosen for this call.

    Args:
        app: The application.

    Returns:
        The running server; call ``stop`` when the test is done.

    Raises:
        ServerStartError: If the server is not listening within ten seconds.
    """
    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + STARTUP_SECONDS
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            server.should_exit = True
            raise ServerStartError(f"The test server did not start on port {port}.")
        time.sleep(0.02)
    return RunningServer(f"http://127.0.0.1:{port}", server, thread)


class BrowserMissingError(RuntimeError):
    """No Chromium could be started for a browser test."""


def launch_chromium(playwright: Any) -> Any:
    """Start headless Chromium, using an installed one when Playwright's own build is absent.

    The browser named by ``PLAYWRIGHT_CHROMIUM_EXECUTABLE`` is used when that is set; otherwise
    Playwright's own is tried, then the newest headless shell under ``~/.cache/ms-playwright``.

    Args:
        playwright: The Playwright object of ``sync_playwright()``.

    Returns:
        The launched browser.

    Raises:
        BrowserMissingError: If no browser can be started; the message says what was tried.
    """
    from playwright.sync_api import Error

    named = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if named:
        return playwright.chromium.launch(executable_path=named)
    try:
        return playwright.chromium.launch()
    except Error as first:
        cache = Path(
            os.environ.get("PLAYWRIGHT_BROWSERS_PATH", Path.home() / ".cache/ms-playwright")
        )
        shells = sorted(
            cache.glob(
                "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"
            )
        )
        if not shells:
            raise BrowserMissingError(
                f"No Chromium is installed for Playwright ({str(first).splitlines()[0]}), and none "
                f"was found under {cache}."
            ) from first
        return playwright.chromium.launch(executable_path=str(shells[-1]))
