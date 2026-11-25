"""A signed brief is never lost to a state move or to a command the shell prints, on topic 03."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

from app_probe_topic import make_probe_topic
from app_shell_support import FSI_COMMON, ShellRun, carrying, running_shell, start_shell, wait_gone

TOPIC_03 = FSI_COMMON.parent / "03_document_summary_agent"
SEED = {"APP_SEED": "compliance-brief", "MODEL_BACKEND": "replay"}
ONE_TOPIC_PATH = f"{FSI_COMMON}:{TOPIC_03}"
DIGEST = re.compile(r"\b[0-9a-f]{16,}\b")
NAV = re.compile(r'<nav class="topics".*?</nav>', re.S)


def digests(folder: Path) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.name != "in-use.lock"
    }


def what_is_found(run: ShellRun) -> dict:
    """Read, through the pages, the signed brief, its sign-off record and its digests."""
    with run.client() as http:
        listing = http.get("/compliance-brief/").text
        threads = list(dict.fromkeys(re.findall(r"/compliance-brief/runs/([\w-]+)", listing)))
        signed = {}
        for thread in threads:
            page = http.get(f"/compliance-brief/runs/{thread}/signed", follow_redirects=True)
            if str(page.url).endswith("/signed"):
                signed[thread] = NAV.sub("", page.text)
        assert len(threads) == 2 and len(signed) == 1, "one signed brief and one open one"
        ((thread, page),) = signed.items()
        assert "Sign-off record" in page and "Dana Whitfield, Head of Compliance" in page
        digests_found = sorted(set(DIGEST.findall(page)))
        assert digests_found, "the sign-off's digest must be on the page"
        return {
            "threads": sorted(threads),
            "signed": thread,
            "page": page,
            "digests": digests_found,
        }


def printed_commands(run: ShellRun) -> list[str]:
    """Return every command a refusal printed, as a person would copy it."""
    commands = []
    for line in run.log.read_text().splitlines():
        if "mkdir -p" in line:
            commands.append(line[line.index("mkdir -p") :].split(" ; then")[0])
    return commands


def follow(commands: list[str]) -> None:
    for command in commands:
        done = subprocess.run(
            ["bash", "-c", command],
            env={"TOPIC": TOPIC_03.name, "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr


def refused(tmp_path, folders, state, **env) -> ShellRun:
    run = start_shell(tmp_path, folders, state=state, wait=False, extra_env=env)
    assert run.process.wait(timeout=120) != 0
    assert wait_gone(carrying(str(tmp_path))) == []
    return run


def test_a_signed_brief_survives_every_state_move_the_shell_suggests(tmp_path):
    probe = make_probe_topic(tmp_path, "09_probe_agent", name="probe", value="p")
    several = [TOPIC_03, probe]
    s_folder, u_folder, v_folder = tmp_path / "S", tmp_path / "U", tmp_path / "V"

    # 1. A folder laid out for several topics, with a signed brief and an open one in topic 03.
    with running_shell(tmp_path, several, state=s_folder, extra_env=SEED) as run:
        first = what_is_found(run)

    # 2. A start with one topic over it is refused and writes nothing.
    before = digests(s_folder)
    one = start_shell(
        tmp_path,
        [TOPIC_03],
        state=s_folder,
        wait=False,
        extra_env={**SEED, "PYTHONPATH": ONE_TOPIC_PATH},
    )
    assert one.process.wait(timeout=120) != 0
    assert digests(s_folder) == before

    # 3. A start with one topic on a folder of its own, then several topics on it: the refusal's
    # move is followed, and the brief, its sign-off and its digests are all found afterwards.
    with running_shell(
        tmp_path, [TOPIC_03], state=u_folder, extra_env={**SEED, "PYTHONPATH": ONE_TOPIC_PATH}
    ) as run:
        alone = what_is_found(run)
    one_topic_files = digests(u_folder)
    stop = refused(tmp_path, several, u_folder, **SEED)
    commands = printed_commands(stop)
    assert len(commands) == 1
    follow(commands)
    assert digests(u_folder / TOPIC_03.name) == one_topic_files, "no file lost or changed"
    with running_shell(tmp_path, several, state=u_folder, extra_env=SEED) as run:
        moved = what_is_found(run)
    assert moved == alone

    # 4. Both layouts present, as a one-topic start over a several-topic folder once left them:
    # whatever the shell prints is followed, and the first folder's signed brief is still there.
    with running_shell(
        tmp_path, [TOPIC_03], state=v_folder, extra_env={"PYTHONPATH": ONE_TOPIC_PATH}
    ):
        pass
    top_level = [p for p in v_folder.iterdir() if p.is_file()]
    assert top_level, "an empty one-topic start leaves files at the top"
    for path in top_level:
        shutil.copy2(path, s_folder / path.name)
    both = digests(s_folder)
    stop = refused(tmp_path, several, s_folder, **SEED)
    follow(printed_commands(stop))
    assert digests(s_folder) == both, "a refusal and the commands it printed change nothing"
    for path in top_level:
        (s_folder / path.name).unlink(missing_ok=True)
    with running_shell(tmp_path, several, state=s_folder, extra_env=SEED) as run:
        again = what_is_found(run)
    assert again == first
