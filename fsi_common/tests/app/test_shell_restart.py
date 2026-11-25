"""A topic whose process ends is started again on a request, at most once a minute, in words."""

from __future__ import annotations

import os
import signal
import time

import httpx
from app_probe_topic import make_broken_topic, make_probe_topic, two_probes
from app_shell_support import is_alive, listening, running_shell, wait_gone


def alive_children(run):
    return [pid for pid in run.children() if is_alive(pid, strict=False)]


def kill_topic(run, http, name):
    victim = next(pid for pid in alive_children(run) if _serves(pid, name))
    os.kill(victim, signal.SIGKILL)
    assert wait_gone([victim], strict=False) == []
    return victim


def wait_for_page(http, path, words, *, seconds=60.0):
    """Ask for a page until its text holds ``words``; return the last answer."""
    deadline = time.monotonic() + seconds
    while True:
        page = http.get(path)
        if words in page.text or time.monotonic() > deadline:
            return page
        time.sleep(0.3)


def test_a_topic_whose_process_dies_is_started_again_on_the_next_request_and_says_so(tmp_path):
    first, second = two_probes(tmp_path)
    with running_shell(tmp_path, [first, second]) as run, run.client() as http:
        assert "Value is a." in http.get("/alpha/").text
        kill_topic(run, http, "alpha")
        page = http.get("/alpha/")
        assert page.status_code == 503
        assert "Alpha stopped and is starting again." in page.text
        assert "Value is b." in http.get("/beta/").text
        back = wait_for_page(http, "/alpha/", "Value is a.")
        assert back.status_code == 200 and "Value is a." in back.text
        assert len(alive_children(run)) == 2
        assert "starting it again" in run.log.read_text()


def test_a_topic_that_dies_again_within_a_minute_is_not_started_a_third_time_and_says_so(tmp_path):
    first, second = two_probes(tmp_path)
    with running_shell(tmp_path, [first, second]) as run, run.client() as http:
        kill_topic(run, http, "alpha")
        http.get("/alpha/")
        assert "Value is a." in wait_for_page(http, "/alpha/", "Value is a.").text
        kill_topic(run, http, "alpha")
        page = http.get("/alpha/")
        assert page.status_code == 503
        assert "Alpha could not be reached. It was started again less than a minute ago." in (
            page.text
        )
        assert len(alive_children(run)) == 1
        assert "Alpha could not be reached." in http.get("/").text
        assert "Value is b." in http.get("/beta/").text


def test_a_topic_that_cannot_start_again_says_so_and_the_other_still_serves(tmp_path):
    first, second = two_probes(tmp_path)
    with running_shell(tmp_path, [first, second]) as run, run.client() as http:
        (first / "review_app" / "broken.flag").write_text("")
        kill_topic(run, http, "alpha")
        assert "starting again" in http.get("/alpha/").text
        page = wait_for_page(http, "/alpha/", "could not be reached")
        assert page.status_code == 503
        assert "Alpha could not be reached. It was started again less than a minute ago." in (
            page.text
        )
        assert "Value is b." in http.get("/beta/").text


def _serves(pid: int, name: str) -> bool:
    address = listening(pid)[0]
    try:
        return httpx.get(f"http://{address}/_shell/topic", timeout=5.0).json()["name"] == name
    except httpx.TransportError:
        return False


def test_the_home_page_alone_starts_a_dead_topic_again(tmp_path):
    first, second = two_probes(tmp_path)
    with running_shell(tmp_path, [first, second]) as run, run.client() as http:
        victim = kill_topic(run, http, "alpha")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and len(alive_children(run)) < 2:
            assert http.get("/").status_code == 200
            time.sleep(0.3)
        assert len(alive_children(run)) == 2 and victim not in alive_children(run)
        assert "starting it again" in run.log.read_text()
        assert "Value is a." in wait_for_page(http, "/alpha/", "Value is a.").text


def test_a_topic_that_never_answered_is_not_started_again_by_any_page(tmp_path):
    working = make_probe_topic(tmp_path, "01_alpha_agent", name="alpha", value="a")
    broken = make_broken_topic(tmp_path, "02_transaction_monitoring_agent")
    with running_shell(tmp_path, [working, broken]) as run, run.client() as http:
        for _ in range(3):
            assert "Transaction monitoring could not be reached." in http.get("/").text
            http.get("/about")
            time.sleep(0.5)
        assert "starting it again" not in run.log.read_text()
        assert len(alive_children(run)) == 1


def test_the_home_page_says_a_topic_is_starting_again_while_it_is(tmp_path):
    first, second = two_probes(tmp_path)
    with running_shell(tmp_path, [first, second]) as run, run.client() as http:
        kill_topic(run, http, "alpha")
        home = http.get("/").text
        assert "Alpha is starting again." in home
        assert "Alpha could not be reached." not in home


def test_a_refused_connection_to_a_topic_is_a_reason_to_check_its_process_and_start_it_again(
    tmp_path, monkeypatch
):
    """The process ends 0.2 s after the refusal, as a killed one does a moment after its socket."""
    import threading

    from starlette.testclient import TestClient

    from fsi_common.app import AppConfig
    from fsi_common.app.shell import create_shell

    first, second = two_probes(tmp_path)
    app = create_shell(AppConfig(secret=b"x", topic_folders=(first, second)))
    shell = app.state.shell
    real_send = shell.client.send
    refused: list[int] = []

    async def send(request, **kwargs):
        if request.url.path.startswith("/alpha") and not refused:
            child = shell.child_at("/alpha")
            refused.append(child.process.pid)
            threading.Timer(0.2, child.process.kill).start()
            raise httpx.ConnectError("refused")
        return await real_send(request, **kwargs)

    monkeypatch.setattr(shell.client, "send", send)
    with TestClient(app) as http:
        page = http.get("/alpha/")
        assert page.status_code == 503
        assert "Alpha stopped and is starting again." in page.text
        assert "Value is a." in wait_for_page(http, "/alpha/", "Value is a.").text


def test_a_read_timeout_is_not_a_reason_to_start_a_topic_again(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from fsi_common.app import AppConfig
    from fsi_common.app.shell import create_shell

    first, second = two_probes(tmp_path)
    app = create_shell(AppConfig(secret=b"x", topic_folders=(first, second)))
    shell = app.state.shell
    real_send = shell.client.send

    async def send(request, **kwargs):
        if request.url.path.startswith("/alpha"):
            raise httpx.ReadTimeout("frozen")
        return await real_send(request, **kwargs)

    monkeypatch.setattr(shell.client, "send", send)
    with TestClient(app) as http:
        pid = shell.child_at("/alpha").process.pid
        page = http.get("/alpha/")
        assert page.status_code == 503 and "Alpha could not be reached." in page.text
        assert "starting again" not in page.text
        assert shell.child_at("/alpha").process.pid == pid


def test_a_topic_that_runs_but_does_not_answer_after_a_restart_is_said_to_run(tmp_path):
    first, second = two_probes(tmp_path)
    with (
        running_shell(tmp_path, [first, second], extra_env={"APP_CHILD_START_SECONDS": "2"}) as run,
        run.client() as http,
    ):
        (first / "review_app" / "slow.flag").write_text("")
        kill_topic(run, http, "alpha")
        assert "starting again" in http.get("/alpha/").text
        time.sleep(3.5)
        page = http.get("/alpha/")
        assert page.status_code == 503
        assert "Alpha could not be reached. It is running but did not answer." in page.text
        assert "less than a minute ago" not in page.text


def test_stopping_the_shell_cancels_a_restart_that_is_waiting(tmp_path):
    import asyncio

    from fsi_common.app import AppConfig
    from fsi_common.app.shell import Shell

    first, _ = two_probes(tmp_path)

    async def run() -> bool:
        shell = Shell(AppConfig(secret=b"x", topic_folders=(first,)), [first])
        task = asyncio.ensure_future(asyncio.sleep(100))
        shell.children[0].restart_task = task
        await shell.stop()
        return task.cancelled()

    assert asyncio.run(run()) is True
