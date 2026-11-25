"""Notebooks 2 and 3 read and write one LangSmith dataset, under one name kept in one place."""

from __future__ import annotations

import re

from notebook_support import NAMES, load
from scripts.run_experiments import DATASET_NAME

from utils.attendee import ATTENDEE


def source(name: str, index: int) -> str:
    return "".join(load(name)["cells"][index]["source"])


def test_the_dataset_notebook_2_makes_is_the_one_named_in_the_scripts_module():
    made = re.search(r'^DATASET_NAME = (f?"[^"]+")$', source(NAMES[1], 3), re.M)
    assert made, "notebook 2 no longer names its dataset on one line"
    assert eval(made.group(1), {"ATTENDEE": ATTENDEE}) == DATASET_NAME  # noqa: S307


def test_notebook_3_takes_its_dataset_name_from_the_scripts_module_and_never_makes_its_own():
    text = source(NAMES[2], 2)
    assert "from scripts.run_experiments import DATASET_NAME" in text
    for index, cell in enumerate(load(NAMES[2])["cells"]):
        if cell["cell_type"] == "code":
            assert not re.search(r"^DATASET_NAME\s*=", "".join(cell["source"]), re.M), index


def test_the_name_carries_the_attendee_so_two_attendees_never_share_a_dataset():
    assert DATASET_NAME == f"transaction-monitoring-{ATTENDEE}"
