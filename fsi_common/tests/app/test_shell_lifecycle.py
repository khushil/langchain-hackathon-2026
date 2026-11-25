"""The shell's children start with it, stop with it, and a failing one costs only its own topic."""

from __future__ import annotations

import signal
import time

from app_probe_topic import make_broken_topic, make_probe_topic, two_probes
from app_shell_support import (
    carrying,
    running_shell,
    start_shell,
    stop_shell,
    wait_gone,
)


def test_stopping_the_shell_with_a_signal_leaves_no_child_alive(tmp_path):
    run = start_shell(tmp_path, two_probes(tmp_path))
    kids = stop_shell(run, signal.SIGTERM)
    assert len(kids) == 2
    assert run.process.returncode in (0, -signal.SIGTERM)
    assert wait_gone(kids) == []


def test_an_interrupt_leaves_no_child_alive_either(tmp_path):
    run = start_shell(tmp_path, two_probes(tmp_path))
    kids = stop_shell(run, signal.SIGINT)
    assert len(kids) == 2
    assert wait_gone(kids) == []


def test_a_shell_that_is_killed_outright_takes_its_children_with_it(tmp_path):
    run = start_shell(tmp_path, two_probes(tmp_path))
    kids = stop_shell(run, signal.SIGKILL)
    assert len(kids) == 2
    assert wait_gone(kids) == []


def test_a_shell_that_cannot_start_leaves_no_child_and_says_why(tmp_path):
    first, second = two_probes(tmp_path)
    run = start_shell(tmp_path, [first, second], extra_env={"APP_SEED": "gamma"}, wait=False)
    assert run.process.wait(timeout=60) != 0
    assert "APP_SEED is 'gamma'" in run.log.read_text() and "topics served" in run.log.read_text()
    assert wait_gone(carrying(str(tmp_path))) == []


def test_a_topic_that_will_not_load_is_named_on_the_home_page_and_the_other_still_serves(tmp_path):
    working = make_probe_topic(
        tmp_path, "01_alpha_agent", name="alpha", value="a", waiting="2", noun="case"
    )
    broken = make_broken_topic(tmp_path, "02_transaction_monitoring_agent")
    with running_shell(tmp_path, [working, broken]) as run, run.client() as http:
        home = http.get("/").text
        assert "Transaction monitoring could not be reached." in home
        assert "2 cases are waiting for a reviewer." in home
        assert "Value is a." in http.get("/alpha/").text
        assert len(run.children()) <= 2


def test_a_topic_that_never_answers_in_time_is_named_and_stopped_with_the_shell(tmp_path):
    working = make_probe_topic(tmp_path, "01_alpha_agent", name="alpha", value="a")
    slow = make_broken_topic(tmp_path, "03_slow_agent", hang_seconds=120)
    started = time.monotonic()
    run = start_shell(tmp_path, [working, slow], extra_env={"APP_CHILD_START_SECONDS": "3"})
    try:
        assert time.monotonic() - started < 40
        with run.client() as http:
            assert "Slow could not be reached." in http.get("/").text
            assert "Value is a." in http.get("/alpha/").text
    finally:
        kids = stop_shell(run)
    assert len(kids) == 2
    assert wait_gone(kids) == []


def test_one_topic_is_served_in_its_own_process_with_its_state_where_it_was(tmp_path):
    only = make_probe_topic(tmp_path, "01_alpha_agent", name="alpha", value="a")
    with running_shell(tmp_path, [only]) as run, run.client() as http:
        assert run.children() == []
        assert "Value is a." in http.get("/alpha/").text
        assert http.get("/alpha/state").json()["folder"] == str(run.state_dir)
        assert (run.state_dir / "marker.txt").read_text() == "alpha"


def test_two_topics_with_one_name_stop_the_start_in_words_and_leave_no_child(tmp_path):
    first = make_probe_topic(tmp_path, "01_alpha_agent", name="same", value="a", prefix="/one")
    second = make_probe_topic(tmp_path, "02_beta_agent", name="same", value="b", prefix="/two")
    run = start_shell(tmp_path, [first, second], wait=False)
    assert run.process.wait(timeout=60) != 0
    assert "Two topics share the name same." in run.log.read_text()
    assert wait_gone(carrying(str(tmp_path))) == []


def test_two_topics_with_one_prefix_stop_the_start_in_words_and_leave_no_child(tmp_path):
    first = make_probe_topic(tmp_path, "01_alpha_agent", name="one", value="a", prefix="/same")
    second = make_probe_topic(tmp_path, "02_beta_agent", name="two", value="b", prefix="/same")
    run = start_shell(tmp_path, [first, second], wait=False)
    assert run.process.wait(timeout=60) != 0
    assert "Two topics share the prefix /same." in run.log.read_text()
    assert wait_gone(carrying(str(tmp_path))) == []
