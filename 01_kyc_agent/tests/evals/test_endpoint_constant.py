"""The EU LangSmith address is written once, in the shared member, and nowhere in this topic."""

from pathlib import Path

TOPIC = Path(__file__).resolve().parents[2]
ADDRESS = "eu.api.smith.langchain.com"


def test_the_address_of_the_eu_workspace_is_not_written_in_this_topic():
    holders = [
        f.relative_to(TOPIC).as_posix()
        for f in TOPIC.rglob("*.py")
        if "tests" not in f.parts and ADDRESS in f.read_text(encoding="utf-8")
    ]
    assert holders == []
