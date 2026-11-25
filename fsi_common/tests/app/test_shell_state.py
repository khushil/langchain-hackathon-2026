"""The state folder: which layouts several topics and one topic accept, and what they never move."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from app_probe_topic import make_probe_topic, two_probes
from app_shell_support import carrying, running_shell, start_shell, wait_gone


def digests(folder: Path) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def test_a_state_folder_with_files_of_a_one_topic_start_stops_a_several_topic_start(tmp_path):
    first, second = two_probes(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    (state / "runs.sqlite").write_text("kept")
    run = start_shell(tmp_path, [first, second], wait=False)
    assert run.process.wait(timeout=60) != 0
    log = run.log.read_text()
    assert str(state) in log and "runs.sqlite" in log
    assert "find" in log and "mv" in log and "01_alpha_agent" in log and "02_beta_agent" in log
    assert (state / "runs.sqlite").read_text() == "kept"
    assert sorted(p.name for p in state.iterdir()) == ["runs.sqlite"]
    assert wait_gone(carrying(str(tmp_path))) == []


def test_a_state_folder_of_subfolders_and_hidden_files_is_accepted(tmp_path):
    first, second = two_probes(tmp_path)
    state = tmp_path / "state"
    (state / "01_alpha_agent").mkdir(parents=True)
    (state / ".gitkeep").write_text("")
    with running_shell(tmp_path, [first, second]) as run, run.client() as http:
        assert "Value is a." in http.get("/alpha/").text


def test_a_state_folder_laid_out_for_several_topics_stops_a_start_with_one(tmp_path):
    only = make_probe_topic(tmp_path, "01_alpha_agent", name="alpha", value="a")
    state = tmp_path / "state"
    (state / "01_alpha_agent").mkdir(parents=True)
    (state / "01_alpha_agent" / "runs.sqlite").write_text("kept")
    before = digests(state)
    run = start_shell(tmp_path, [only], wait=False)
    assert run.process.wait(timeout=60) != 0
    log = run.log.read_text()
    assert str(state) in log and "01_alpha_agent" in log
    assert "several topics" in log and f"{state}/01_alpha_agent" in log
    assert digests(state) == before, "a refused start must write nothing"


def test_both_layouts_present_are_refused_with_no_move_offered(tmp_path):
    first, second = two_probes(tmp_path)
    state = tmp_path / "state"
    (state / "01_alpha_agent").mkdir(parents=True)
    (state / "01_alpha_agent" / "runs.sqlite").write_text("the topic's own")
    (state / "runs.sqlite").write_text("from a start with one topic")
    before = digests(state)
    run = start_shell(tmp_path, [first, second], wait=False)
    assert run.process.wait(timeout=60) != 0
    log = run.log.read_text()
    assert "both" in log and "choose" in log
    assert "mv " not in log and "find " not in log, "no command may be offered here"
    assert digests(state) == before
    assert wait_gone(carrying(str(tmp_path))) == []


def test_the_move_the_product_prints_loses_nothing_and_never_overwrites(tmp_path):
    first, second = two_probes(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    (state / "runs.sqlite").write_text("from a start with one topic")
    (state / "seeded.json").write_text("{}")
    refused = start_shell(tmp_path, [first, second], wait=False)
    assert refused.process.wait(timeout=60) != 0
    lines = [line for line in refused.log.read_text().splitlines() if "mkdir -p" in line]
    assert len(lines) == 1 and "mv -n" in lines[0]
    command = lines[0][lines[0].index("mkdir -p") :].split(" ; then")[0]
    done = subprocess.run(
        ["bash", "-c", command],
        env={"TOPIC": "01_alpha_agent", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    kept = state / "01_alpha_agent"
    assert (kept / "runs.sqlite").read_text() == "from a start with one topic"
    assert (kept / "seeded.json").read_text() == "{}"
    assert sorted(p.name for p in state.iterdir()) == ["01_alpha_agent"]
    with running_shell(tmp_path, [first, second]) as run, run.client() as http:
        assert "Value is a." in http.get("/alpha/").text
    assert (kept / "runs.sqlite").read_text() == "from a start with one topic"


def test_the_printed_move_does_not_replace_a_file_that_is_already_there(tmp_path):
    state = tmp_path / "state"
    target = state / "01_alpha_agent"
    target.mkdir(parents=True)
    (state / "runs.sqlite").write_text("the new one")
    (target / "runs.sqlite").write_text("the old one")
    subprocess.run(
        ["bash", "-c", f"find {state} -maxdepth 1 -type f -exec mv -n -t {target} {{}} +"],
        check=False,  # recent versions of mv say they skipped a file by failing
    )
    assert (target / "runs.sqlite").read_text() == "the old one"
    assert (state / "runs.sqlite").read_text() == "the new one", "the skipped file stays put"
