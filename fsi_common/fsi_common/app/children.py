"""One process for each topic: how it is started, what it is given and how it is stopped."""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import socket
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from fsi_common.app.config import AppConfig
from fsi_common.app.topic_info import TopicInfo, title_from_folder

log = logging.getLogger(__name__)

CHILD_MODULE = "fsi_common.app.topic_server"
STOP_SECONDS = 10.0
LISTEN_BACKLOG = 128
FSI_COMMON_DIR = Path(__file__).resolve().parents[2]

# Settings that belong to one process and are never inherited from the shell's own environment.
OWN_SETTINGS = (
    "APP_TOPICS",
    "APP_SEED",
    "APP_STATE_DIR",
    "APP_LISTEN_FD",
    "APP_PARENT_PID",
    "PYTHONPATH",
    "PYTHONHOME",
    "APP_SECRET",
)


class ChildStartError(RuntimeError):
    """A topic's process could not be started; the message names the folder and the cause."""


class StateLayoutError(RuntimeError):
    """The state folder holds a one-topic start's files, which several topics would not read."""


def shared_secret(config: AppConfig) -> str:
    """Return the text every process of one application signs sessions with.

    The configured secret may be random bytes, which an environment variable cannot hold, so the
    shell and its children all sign with the text of its hexadecimal form.

    Args:
        config: The shell's settings.

    Returns:
        The signing text.
    """
    return config.secret.hex()


def worker_environment(folder: Path) -> dict[str, str]:
    """Make the environment of a process that works for one topic and no other.

    The path holds this package's folder and the topic's own folder and nothing else of the
    shell's, so no other topic's modules can be imported, and no secret or per-process setting
    of the parent is carried over.

    Args:
        folder: The topic folder.

    Returns:
        The environment.
    """
    env = {k: v for k, v in os.environ.items() if k not in OWN_SETTINGS}
    env["PYTHONPATH"] = os.pathsep.join([str(FSI_COMMON_DIR), str(folder)])
    return env


def child_environment(
    config: AppConfig, folder: Path, *, state: Path | None, port: int, fd: int, seed: str
) -> dict[str, str]:
    """Make the environment of a topic's process.

    The signing secret is passed here and nowhere else.

    Args:
        config: The shell's settings.
        folder: The topic folder.
        state: The topic's own state folder, or None when the shell keeps no state in files.
        port: The loopback port of the socket the process is given.
        fd: The number of that socket in the process.
        seed: The ``APP_SEED`` the process is given: the names of the topics to seed, or empty.

    Returns:
        The environment.
    """
    env = worker_environment(folder)
    env.update(
        {
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(port),
            "APP_TOPICS": str(folder),
            "APP_SECRET": shared_secret(config),
            "APP_COOKIE": config.cookie_name,
            "APP_LISTEN_FD": str(fd),
            "APP_PARENT_PID": str(os.getpid()),
        }
    )
    if seed:
        env["APP_SEED"] = seed
    if state is not None:
        env["APP_STATE_DIR"] = str(state)
    return env


@dataclass
class TopicChild:
    """One topic's process and what the shell has learned of the topic from it."""

    folder: Path
    state: Path | None
    process: subprocess.Popen | None = None
    port: int | None = None
    info: TopicInfo | None = None
    waiting: int | None = None
    answering: bool = False
    restarted_at: float | None = None
    restart_task: asyncio.Task | None = None
    _stopped: bool = field(default=False, repr=False)

    @property
    def title(self) -> str:
        """The topic's own title once it has answered, else one made from its folder's name."""
        return self.info.title if self.info else title_from_folder(self.folder)

    @property
    def base_url(self) -> str:
        """The loopback address of the process."""
        return f"http://127.0.0.1:{self.port}"

    def running(self) -> bool:
        """Say whether the process was started and has not ended."""
        return self.process is not None and self.process.poll() is None

    def start(self, config: AppConfig) -> None:
        """Start the process on a loopback socket the shell makes and then lets go of.

        The socket is made here and handed over by number, so the process can listen nowhere
        else, and when it ends the port is closed and a request is refused at once.

        Args:
            config: The shell's settings.

        Raises:
            ChildStartError: If the socket or the process cannot be made.
        """
        self.answering = False
        self._stopped = False
        try:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(LISTEN_BACKLOG)
                self.port = listener.getsockname()[1]
                env = child_environment(
                    config,
                    self.folder,
                    state=self.state,
                    port=self.port,
                    fd=listener.fileno(),
                    seed=self._seed_for(config),
                )
                self.process = subprocess.Popen(  # noqa: S603 - our own interpreter and module
                    [sys.executable, "-P", "-m", CHILD_MODULE],
                    env=env,
                    pass_fds=(listener.fileno(),),
                )
        except OSError as exc:
            raise ChildStartError(
                f"The process for {self.folder} could not be started: {exc}"
            ) from exc

    def _seed_for(self, config: AppConfig) -> str:
        """Say which ``APP_SEED`` this topic's process is given.

        A topic that has answered once is given its own name, when the setting lists it, and no
        other. Before that its name is not known, so it is given the whole setting and the
        process takes only its own name from it.
        """
        if self.info is None:
            return config.seed
        return self.info.name if self.info.name in config.seeds else ""

    def ask_to_stop(self) -> None:
        """Send the process the request to finish, if it is running."""
        if self.running() and not self._stopped:
            self._stopped = True
            self.process.terminate()

    def wait_stopped(self) -> None:
        """Wait for the process to end, ending it by force after ``STOP_SECONDS``."""
        if self.process is None:
            return
        try:
            self.process.wait(timeout=STOP_SECONDS)
        except subprocess.TimeoutExpired:
            log.warning("The process for %s did not stop in time and was ended.", self.folder)
            self.process.kill()
            self.process.wait()


def make_children(config: AppConfig, folders: Sequence[Path]) -> list[TopicChild]:
    """Make a record for each topic folder, each with its own state folder.

    Args:
        config: The shell's settings.
        folders: The topic folders.

    Returns:
        One child record for each folder, not yet started.
    """
    state_root = config.state_dir
    return [
        TopicChild(folder=f.resolve(), state=state_root / f.resolve().name if state_root else None)
        for f in folders
    ]


def stop_children(children: Sequence[TopicChild]) -> None:
    """Stop every process the shell started, all asked together and then waited for."""
    for child in children:
        child.ask_to_stop()
    for child in children:
        child.wait_stopped()


def _holds_files(folder: Path) -> bool:
    return folder.is_dir() and any(p.is_file() for p in folder.rglob("*"))


def check_state_layout(state_dir: Path | None, folders: Sequence[Path]) -> None:
    """Refuse a state folder that still holds the files of a start with one topic.

    With several topics each keeps its state in a subfolder named for its topic folder, so files
    directly in the state folder would be passed over and fresh state made beside them, unseen.
    Nothing is moved or deleted, and no move is offered that could replace state: when a topic's
    subfolder already holds files too, both copies exist and a person must choose.

    Args:
        state_dir: The state folder, or None when the shell keeps no state in files.
        folders: The topic folders served.

    Raises:
        StateLayoutError: If the state folder holds a file other than a hidden one; the message
            names the folder and either the one move that cannot replace anything, or, when
            both layouts hold state, that a person must choose.
    """
    if state_dir is None or not state_dir.is_dir():
        return
    files = sorted(
        p.name for p in state_dir.iterdir() if p.is_file() and not p.name.startswith(".")
    )
    if not files:
        return
    shown = f"{', '.join(files[:3])}{', and more' if len(files) > 3 else ''}"
    names = [f.resolve().name for f in folders]
    both = [n for n in names if _holds_files(state_dir / n)]
    if both:
        raise StateLayoutError(
            f"APP_STATE_DIR {state_dir} holds both layouts: files of a start with one topic "
            f"({shown}) and state of its own in the subfolders {', '.join(both)}. No move is "
            "offered here, because any move could replace state. A person must choose which to "
            "keep: look at both, then move or delete by hand, and start again. Nothing was "
            "moved or deleted."
        )
    where = shlex.quote(str(state_dir))
    raise StateLayoutError(
        f"APP_STATE_DIR {state_dir} holds files of a start with one topic ({shown}). With "
        "several topics each keeps its state in a subfolder named for its topic folder, so "
        "these files would not be read and new state would be made beside them. Move them into "
        f"the subfolder of the topic that wrote them, with TOPIC set to one of {', '.join(names)}: "
        f"mkdir -p {where}/$TOPIC && "
        f"find {where} -maxdepth 1 -type f -exec mv -n -t {where}/$TOPIC {{}} + ; "
        "then start again. Nothing was moved or deleted."
    )


def check_single_topic_layout(state_dir: Path | None, folder: Path, others: Sequence[str]) -> None:
    """Refuse a state folder laid out for several topics when only one topic is started.

    A start with one topic keeps its state directly in the state folder, so over subfolders it
    would start empty beside them and a later start with several topics would meet both layouts.

    Args:
        state_dir: The state folder, or None when no state is kept in files.
        folder: The one topic folder served.
        others: The names of other topic folders that are built.

    Raises:
        StateLayoutError: If a subfolder named for a topic folder holds files; the message names
            them and says how to start the topics together or serve this one from its subfolder.
    """
    if state_dir is None or not state_dir.is_dir():
        return
    names = sorted({folder.resolve().name, *others})
    found = [n for n in names if _holds_files(state_dir / n)]
    if found:
        raise StateLayoutError(
            f"APP_STATE_DIR {state_dir} holds state laid out for several topics (subfolders "
            f"{', '.join(found)}). A start with one topic keeps its state directly in the "
            "folder, so it would start empty beside them. Start the topics together, so that "
            "the shell serves them, or serve this topic alone from its own subfolder with "
            f"APP_STATE_DIR={state_dir}/{folder.resolve().name}. Nothing was moved or deleted."
        )
