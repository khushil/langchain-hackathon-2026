"""The offline export when several topics are built: each is read in a process of its own."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from fsi_common.app.children import worker_environment

NOT_THIS_TOPIC = 3
WORKER_SECONDS = 1800.0


@dataclass(frozen=True)
class WorkerAnswer:
    """What the processes said: the file's report when one wrote it, else why none did."""

    written: bool
    code: int
    out: str
    err: str
    names: tuple[str, ...] = ()


def ask_worker(
    folder: Path, *, topic: str, out: Path, reviewer: Sequence[str]
) -> subprocess.CompletedProcess[str]:
    """Run the exporter for one topic folder in a process that holds that folder alone.

    Args:
        folder: The topic folder.
        topic: The name of the topic wanted.
        out: The file to write.
        reviewer: The reviewer's name and role.

    Returns:
        The finished process. It exits 0 when the folder is the topic wanted and the file was
        written, ``NOT_THIS_TOPIC`` with the folder's topic name on standard output when it is
        another, and 1 with the reason on standard error when it could not be exported.

    Raises:
        subprocess.TimeoutExpired: If the process takes longer than ``WORKER_SECONDS``.
    """
    command = [
        sys.executable,
        "-P",
        "-m",
        "fsi_common.app.offline",
        "--folder",
        str(folder),
        "--topic",
        topic,
        "--out",
        str(out),
        "--reviewer-name",
        reviewer[0],
        "--reviewer-role",
        reviewer[1],
    ]
    return subprocess.run(  # noqa: S603 - our own interpreter and module
        command,
        env=worker_environment(folder),
        capture_output=True,
        text=True,
        timeout=WORKER_SECONDS,
        check=False,
    )


def export_in_processes(
    folders: Sequence[Path], *, topic: str, out: Path, reviewer: Sequence[str]
) -> WorkerAnswer:
    """Find the topic among the folders and write its file, each folder read in its own process.

    Topics keep the starter's package names, so two cannot be imported into one process.

    Args:
        folders: The topic folders that have an offline part.
        topic: The name of the topic wanted.
        out: The file to write.
        reviewer: The reviewer's name and role.

    Returns:
        The answer of the process that wrote the file. When none did, ``written=False`` with
        ``code`` 1, the reasons of the folders that failed (a topic that cannot be read does not
        stop another's export) and the names of the topics that were read.
    """
    names: list[str] = []
    failures: list[str] = []
    for folder in folders:
        done = ask_worker(folder, topic=topic, out=out, reviewer=reviewer)
        if done.returncode == NOT_THIS_TOPIC:
            names.append(done.stdout.strip())
        elif done.returncode == 0:
            return WorkerAnswer(True, 0, done.stdout, done.stderr)
        else:
            failures.append(done.stderr)
    if failures:
        return WorkerAnswer(False, 1, "", "".join(failures), tuple(names))
    return WorkerAnswer(False, 1, "", "", tuple(names))
