"""The EU LangSmith address is written once, and the run service's protocol names every call."""

from pathlib import Path

TOPIC = Path(__file__).resolve().parents[2]
SHARED = TOPIC.parent / "fsi_common" / "fsi_common"
ADDRESS = "eu.api.smith.langchain.com"


def test_the_address_of_the_eu_workspace_is_defined_in_one_place_only():
    files = [
        f
        for root in (TOPIC, SHARED)
        for f in root.rglob("*.py")
        if "tests" not in f.parts and ADDRESS in f.read_text(encoding="utf-8")
    ]
    assert [f.relative_to(TOPIC.parent).as_posix() for f in files] == [
        "fsi_common/fsi_common/evals/upload.py"
    ]


def test_the_run_service_protocol_declares_the_root_run_the_sign_route_reads():
    from review_app.service import RunsService

    assert callable(getattr(RunsService, "root_run", None))
