"""No drafting note stays in product text: no reminder, stub marker or 'add when' left in code."""

import re
from pathlib import Path

import pytest

from utils import PROJECT_ROOT

NOTE = re.compile(
    r"\b(ponytail|TODO|FIXME|XXX|HACK|add when|for now|stub|placeholder)\b", re.IGNORECASE
)
FOLDERS = ("context", "workflow", "review_app", "evals", "utils/models.py", "utils/records.py")


def notes_in(text: str) -> list[str]:
    """Return each line of a text that reads as a drafting note."""
    return [line.strip() for line in text.splitlines() if NOTE.search(line)]


def product_files() -> list[Path]:
    files: list[Path] = []
    for folder in FOLDERS:
        path = PROJECT_ROOT / folder
        files += (
            [path]
            if path.is_file()
            else sorted(
                p for p in path.rglob("*") if p.suffix in {".py", ".html", ".md", ".json", ".css"}
            )
        )
    return files


@pytest.mark.parametrize(
    "path", product_files(), ids=lambda p: p.relative_to(PROJECT_ROOT).as_posix()
)
def test_a_product_file_holds_no_drafting_note(path):
    assert notes_in(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "plant",
    ["x = 1  # ponytail: add later", "# TODO fix", "return None  # stub", "# for now only this"],
)
def test_the_scan_finds_each_planted_note(plant):
    assert notes_in(plant)
