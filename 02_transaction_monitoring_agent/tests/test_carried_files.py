"""The starter's files that this topic carries unchanged are still its bytes, digest for digest.

The digests were taken from the starter at the commit the repository README names. A change to
one of these files is a change to the starter's material, and the README lists the files this
topic changes: this test fails until a changed file is moved to that list.
"""

import hashlib
import re

import pytest

from utils import PROJECT_ROOT

CARRIED = {
    "instructions.md": "9731c4ae5b4ba6eae286333fa8a4c30157cd750f0526e6921bb7d0c6e28bf87c",
    "tools/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "tools/transactions.py": "710cd138ecb69ac99dc523cdedaa5055a7ba28fb0fe6fa19e143c23472743fe7",
    "tools/customers.py": "f0f1f86eb8da2706cd2729e935b3104208b91aba07831f04ff35f52c7b634b10",
    "tools/decisions.py": "041139a2c9ed1dfd8bda240b5d7849affb030252d278ee1c6c4dbee512e3f4dd",
    "evals/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "evals/scoring_evals.py": "a80af788d7ba9333307c6741c7be3d477be0fb83539c9d5ce685cf7e4dd21af6",
    "scripts/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "utils/__init__.py": "f241e31e3428873e08ae07e8d35d74adb600fffb8365afa9720566a012dcbe30",
    "utils/db.py": "8f00a2e608897b285397dac624b0f312a0662d91bac0ea3173fe67ba4b8e1bcd",
    "utils/state.py": "38cb3ff22af981728fc52e228f182718aea8562275eddefeaaab74a3eb8e2983",
    "utils/transaction_processing.py": "7fe76471ae7ef3953be30d27c139247f8e65ea6c6a7d7fa48529ad181ca3e77b",
    "utils/attendee.py": "0ddb2c9d781bc8ed96b040af51a14b4953ef904db600fbe3d2c70fbf3ad53042",
    "data/transactions.jsonl": "733d21f010c0f0440cc45a5a66b65da5c1a882b852815d8980f91eebebeb3a63",
    "data/customer_profiles.jsonl": "65f11e31dcba004ab1bb17e832e9d6ce098bc26ce5c1ad27ea7a2ea131d27f5a",
    "data/analyst_labels.jsonl": "31cd10e3c3bf9aa33ad529c0aa95ea9500fdf3ecf6f569d6b6a4a19a22ce8312",
    "data/reviewer_answers.jsonl": "25a1f8d4cf6f1d85ac277757dfceb8ad0e684c26e46c0ae77df7f8031be15eb0",
    "data/simulated_annotations.jsonl": "d181a9160d9fe92199e6dc785fae778ac8d1fab24dfd8ce9f0517c41ad8c825a",
    "images/architecture.png": "0ff361b4d7a357948138cb8b986c546ee51e86700b0cd4e557d9f7dbd6b06f2a",
    "images/eval_loop.png": "fd7a0504340df86ae85cc1aad2b7aaa08186781995c1bee99fd036002ff678ca",
}


@pytest.mark.parametrize("name", sorted(CARRIED))
def test_a_carried_file_is_the_starters_bytes(name):
    digest = hashlib.sha256((PROJECT_ROOT / name).read_bytes()).hexdigest()
    assert digest == CARRIED[name], f"{name} is not the starter's file any more"


def test_twenty_files_are_carried_unchanged_and_none_is_missing():
    assert len(CARRIED) == 20
    assert all((PROJECT_ROOT / name).is_file() for name in CARRIED)


def test_the_repository_readme_lists_the_twenty_carried_files_by_name():
    readme = (PROJECT_ROOT.parent / "README.md").read_text(encoding="utf-8")
    section = readme.split("In topic 02, these files are the starter's, byte for byte:", 1)[1]
    listed = set()
    for line in section.split("\n\n", 2)[1].splitlines():
        listed.update(re.findall(r"`([^`]+)`", line))
    assert listed == set(CARRIED)
