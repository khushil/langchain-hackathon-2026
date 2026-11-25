"""The compliance brief and transaction monitoring are served from one address.

Each topic folder has its own ``utils``, ``workflow``, ``context``, ``evals`` and ``review_app``, so
one process cannot hold two of them. The application runs each topic in a process of its own behind
one address; this test starts that application on loopback with both topics and reads each topic's
home page through it.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

TOPIC = Path(__file__).resolve().parents[1]
REPO = TOPIC.parent
START_TIMEOUT_S = 180


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def fetch(port: int, path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=30) as reply:
            return reply.status, reply.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


@pytest.fixture(scope="module")
def shell(tmp_path_factory):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LANGSMITH_", "LANGCHAIN_", "MODEL_", "APP_"))
    }
    port = free_port()
    env |= {
        "PYTHONPATH": str(REPO / "fsi_common"),
        "LANGSMITH_TRACING": "false",
        "MODEL_BACKEND": "replay",
        "APP_TOPICS": os.pathsep.join([str(REPO / "03_document_summary_agent"), str(TOPIC)]),
        "APP_HOST": "127.0.0.1",
        "APP_PORT": str(port),
        "APP_SECRET": "two-topics",
        "APP_STATE_DIR": str(tmp_path_factory.mktemp("state")),
        "APP_SEED": "transaction-monitoring",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "fsi_common.app"],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("the application stopped while starting")
            try:
                if fetch(port, "/")[0] == 200:
                    break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("the application did not answer in time")
        yield port
    finally:
        process.terminate()
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def test_the_home_page_counts_the_waiting_review_and_names_both_topics(shell):
    status, page = fetch(shell, "/")
    assert status == 200
    assert "1 customer review is waiting for a reviewer." in page
    assert "Compliance brief" in page and "Transaction monitoring" in page


def test_each_topics_list_answers_through_the_one_address(shell):
    status, brief = fetch(shell, "/compliance-brief/")
    assert status == 200 and "Compliance brief" in brief
    status, monitoring = fetch(shell, "/transaction-monitoring/")
    assert status == 200
    assert "2 runs so far: 1 waiting for a reviewer, 1 signed." in monitoring
    assert monitoring.count('data-hook="mark"') >= 15
