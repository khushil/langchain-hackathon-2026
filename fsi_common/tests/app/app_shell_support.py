"""Helpers for the shell's process tests: probe topics, a shell as a process, procfs reads."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from fsi_common.app.testing import free_port

FSI_COMMON = Path(__file__).resolve().parents[2]
START_SECONDS = 60.0
# Every shell a test started, so that a test that fails part way still has its shell stopped.
OPEN_RUNS: list = []


@dataclass
class ShellRun:
    """A shell started as its own process, with what a test needs to look at it."""

    process: subprocess.Popen
    port: int
    log: Path
    secret: str
    state_dir: Path
    stopped: bool = field(default=False)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def pid(self) -> int:
        return self.process.pid

    def client(self) -> httpx.Client:
        return httpx.Client(base_url=self.url, timeout=30.0, follow_redirects=False)

    def children(self) -> list[int]:
        return children_of(self.pid)


def start_shell(
    root: Path,
    folders: Sequence[Path],
    *,
    secret: str = "probe-signing-8f3a1c",
    extra_env: dict[str, str] | None = None,
    wait: bool = True,
    register: bool = True,
    state: Path | None = None,
) -> ShellRun:
    """Start ``python -m fsi_common.app`` for the folders, on a free loopback port."""
    port = free_port()
    state_dir = state or root / "state"
    log = root / f"shell-{port}.log"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(
        {
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(port),
            "APP_TOPICS": os.pathsep.join(str(f) for f in folders),
            "APP_SECRET": secret,
            "APP_STATE_DIR": str(state_dir),
            "APP_CHILD_START_SECONDS": "30",
            "PYTHONPATH": str(FSI_COMMON),
            "LANGSMITH_TRACING": "false",
            "LANGCHAIN_TRACING_V2": "false",
            **(extra_env or {}),
        }
    )
    with log.open("wb") as sink:
        process = subprocess.Popen(
            [sys.executable, "-m", "fsi_common.app"], env=env, stdout=sink, stderr=sink
        )
    run = ShellRun(process, port, log, secret, state_dir)
    if register:
        OPEN_RUNS.append(run)
    if wait:
        try:
            wait_until_serving(run)
        except AssertionError:
            stop_shell(run)
            raise
    return run


def wait_until_serving(run: ShellRun) -> None:
    """Wait for the shell's public port to answer, failing with the log if the process ends."""
    deadline = time.monotonic() + START_SECONDS
    while time.monotonic() < deadline:
        if run.process.poll() is not None:
            raise AssertionError(f"the shell ended with {run.process.returncode}:\n{log_text(run)}")
        try:
            httpx.get(f"{run.url}/static/app.css", timeout=2.0)
            return
        except httpx.TransportError:
            time.sleep(0.1)
    raise AssertionError(f"the shell did not answer in time:\n{log_text(run)}")


def stop_open_shells() -> None:
    """Stop each shell a test started and did not stop, by the PID it was started with."""
    while OPEN_RUNS:
        run = OPEN_RUNS.pop()
        if not run.stopped:
            stop_shell(run)


def log_text(run: ShellRun) -> str:
    return run.log.read_text(errors="replace")


def stop_shell(run: ShellRun, sig: int = signal.SIGTERM) -> list[int]:
    """Stop the shell by its PID and return the children it had, so a test can check them gone."""
    kids = run.children() if run.process.poll() is None else []
    if run.process.poll() is None:
        run.process.send_signal(sig)
        try:
            run.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            run.process.kill()
            run.process.wait(timeout=10)
    run.stopped = True
    return kids


@contextmanager
def running_shell(root: Path, folders: Sequence[Path], **kwargs) -> Iterator[ShellRun]:
    """Run a shell for the length of a block and stop it after, whatever the block does."""
    run = start_shell(root, folders, register=False, **kwargs)
    try:
        yield run
    finally:
        if not run.stopped:
            stop_shell(run)


def children_of(pid: int) -> list[int]:
    """Return the PIDs whose parent is ``pid``, read from the process table."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        if int(stat.rsplit(")", 1)[1].split()[1]) == pid:
            found.append(int(entry.name))
    return sorted(found)


def is_alive(pid: int, *, strict: bool = True) -> bool:
    """Say whether a process exists and has not finished dying.

    A killed process shows as a zombie while its other threads are still ending, and its parent
    cannot collect it until they have. ``strict`` counts such a zombie as alive, which the stop
    and kill tests want; without it a zombie is dead, the moment a request can meet in a restart.
    """
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        threads = len(os.listdir(f"/proc/{pid}/task"))
    except OSError:
        return False
    return state != "Z" or (strict and threads > 1)


def wait_gone(pids: Sequence[int], seconds: float = 10.0, *, strict: bool = True) -> list[int]:
    """Wait for processes to end and return those still alive after ``seconds``."""
    deadline = time.monotonic() + seconds
    alive = [p for p in pids if is_alive(p, strict=strict)]
    while alive and time.monotonic() < deadline:
        time.sleep(0.05)
        alive = [p for p in alive if is_alive(p, strict=strict)]
    return alive


def carrying(text: str) -> list[int]:
    """Return the PIDs of this user's processes whose environment holds ``text``.

    A test names a folder of its own in ``APP_TOPICS``, so the processes that carry it are the
    shell it started and the children that shell started, found without matching any name.
    """
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if text.encode() in (entry / "environ").read_bytes() and is_alive(int(entry.name)):
                found.append(int(entry.name))
        except OSError:
            continue
    return found


def command_line(pid: int) -> str:
    return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")


def listening(pid: int) -> list[str]:
    """Return ``ip:port`` for each TCP socket ``pid`` listens on (IPv6 ones as ``v6:hex:port``)."""
    inodes = set()
    for fd in Path(f"/proc/{pid}/fd").iterdir():
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.startswith("socket:["):
            inodes.add(target[8:-1])
    found = []
    for table, six in (("tcp", False), ("tcp6", True)):
        for line in Path(f"/proc/net/{table}").read_text().splitlines()[1:]:
            parts = line.split()
            if parts[3] != "0A" or parts[9] not in inodes:
                continue
            host, port = parts[1].split(":")
            if six:
                found.append(f"v6:{host}:{int(port, 16)}")
            else:
                found.append(f"{socket.inet_ntoa(bytes.fromhex(host)[::-1])}:{int(port, 16)}")
    return sorted(found)
