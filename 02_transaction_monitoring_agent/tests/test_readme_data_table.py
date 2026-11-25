"""The repository README's data table lists every data file of this topic, and each row exists."""

import re
from pathlib import Path

TOPIC = Path(__file__).resolve().parents[1]
README = TOPIC.parent / "README.md"
FOLDER = TOPIC.name
PLACES = ("data", "evals/data")


def table_rows() -> list[str]:
    section = README.read_text(encoding="utf-8").split("## The data and its terms", 1)[1]
    section = section.split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        if line.startswith("| `"):
            rows.extend(re.findall(r"`([^`]+)`", line.split(" | ")[0]))
    return [row for row in rows if row.startswith(FOLDER + "/")]


def test_every_data_file_of_the_topic_is_in_the_readme_data_table():
    listed = table_rows()
    files = sorted(
        p.relative_to(TOPIC.parent).as_posix()
        for place in PLACES
        for p in (TOPIC / place).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    assert files
    missing = [
        f for f in files if not any(f == r or (r.endswith("/") and f.startswith(r)) for r in listed)
    ]
    assert not missing, f"{len(missing)} of {len(files)} data files are not in the table: {missing}"


def test_every_path_of_the_topic_the_table_names_exists():
    for path in table_rows():
        assert (TOPIC.parent / path).exists(), path
