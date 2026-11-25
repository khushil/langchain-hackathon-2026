"""Two topics served by one application must each keep their own modules.

Each topic folder has its own ``utils``, ``workflow``, ``context``, ``evals`` and ``review_app``, so
the shell has to load a topic's modules apart from another's. Until it does, loading the
compliance brief and transaction monitoring into one process fails, and this test is an expected
failure; the day the shell isolates topics, it passes, the marker is then wrong, and the run fails
until the marker is removed.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOPIC = Path(__file__).resolve().parents[1]
REPO = TOPIC.parent
CHECK = """
import json, os, sys
from pathlib import Path
from starlette.testclient import TestClient
from fsi_common.app import AppConfig, create_app
folders = tuple(Path(p) for p in sys.argv[1:])
app = create_app(AppConfig(secret=b"two-topics", topic_folders=folders))
client = TestClient(app)
pages = ["/", "/about"] + [t.prefix + "/" for t in app.state.topics]
print(json.dumps({"pages": {p: client.get(p).status_code for p in pages},
                  "topics": [t.name for t in app.state.topics]}))
"""


@pytest.mark.xfail(
    strict=True,
    reason="the shell loads every topic's modules under one set of names, so a second topic "
    "meets the first topic's utils, workflow and context",
)
def test_the_compliance_brief_and_transaction_monitoring_serve_from_one_application():
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LANGSMITH_", "LANGCHAIN_", "MODEL_"))
    }
    env |= {"PYTHONPATH": str(REPO / "fsi_common"), "LANGSMITH_TRACING": "false"}
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            CHECK,
            str(REPO / "03_document_summary_agent"),
            str(TOPIC),
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr[-600:]
    answered = json.loads(done.stdout.strip().splitlines()[-1])
    assert answered["topics"] == ["compliance-brief", "transaction-monitoring"]
    assert set(answered["pages"].values()) == {200}
