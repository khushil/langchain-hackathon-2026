"""Tests that every seed's provision quote is the regulation's own text, in its provision's unit.

The regulations are read by the topic's regulation reader. DORA and the AI Act are held in the
repository; SS1/23 is not, so its seeds are checked where its fetched copy is present. A missing
copy fails under ``REQUIRE_REGULATIONS=1``, which the gate sets, and is skipped with the reason
anywhere else. Each test states how many quotes it checked.
"""

import os
import re

import pytest
from policy_support import read_seeds

from context.regulations import manifest, readers
from context.text import contains_word_for_word

KEYS = {"DORA": "DORA", "AI Act": "AI-ACT", "SS1/23": "SS1-23"}
_TAIL = re.compile(r"(, (first|second|third) subparagraph)?(, point \([a-z]+\)(\([ivx]+\))?)?$")


def _available(key: str) -> bool:
    entry = manifest.load_manifest().get(key)
    if entry.text_file:
        return (manifest.REGULATIONS_DIR / entry.text_file).exists()
    return (manifest.CACHE_DIR / entry.cache_file).exists()


def _read(regulation: str):
    key = KEYS[regulation]
    if not _available(key):
        message = (
            f"{regulation} is not held in the repository and its fetched copy is absent; "
            "run python -m context.regulations fetch to check its seeds"
        )
        if os.environ.get("REQUIRE_REGULATIONS"):
            pytest.fail(message)
        pytest.skip(message)
    return readers.read_regulation(key)


def unit_label(provision: str) -> str:
    """Return the label of the unit that holds a provision as a seed names it.

    Points, sub-points and subparagraphs sit inside a paragraph's unit; an SS1/23 sub-principle
    named whole, such as ``Principle 5.1``, is the prefix of its points' labels.

    Args:
        provision: The provision as the seed register names it, for example
            ``Article 30(3), point (e)(i)``.

    Returns:
        The label, for example ``Article 30(3)``.
    """
    label = _TAIL.sub("", provision)
    label = re.sub(r"^(Principle \d\.\d\([a-z]\))\([ivx]+\)$", r"\1", label)
    return "Paragraph" + label.removeprefix("paragraph") if label.startswith("paragraph") else label


def _units_for(read, provision: str) -> list:
    label = unit_label(provision)
    whole = re.fullmatch(r"Principle \d\.\d", label) is not None
    return [
        u for u in read.items if u.label == label or (whole and u.label.startswith(f"{label}("))
    ]


@pytest.mark.parametrize("regulation", list(KEYS))
def test_every_provision_quote_is_in_its_provision_unit_and_in_no_other(regulation):
    read = _read(regulation)
    seeds = [row for row in read_seeds()[1] if row["regulation"] == regulation]
    assert seeds, regulation
    checked = 0
    for row in seeds:
        own = _units_for(read, row["provision"])
        assert own, f"{row['seed_id']}: the reader has no unit for {row['provision']}"
        quote = row["provision_quote"]
        assert any(contains_word_for_word(quote, u.text) for u in own), (
            f"{row['seed_id']}: the quote is not word for word in {row['provision']}"
        )
        elsewhere = [
            u.label for u in read.items if u not in own and contains_word_for_word(quote, u.text)
        ]
        assert not elsewhere, f"{row['seed_id']}: the quote also occurs in {elsewhere}"
        checked += 1
    assert checked == len(seeds)
    print(f"{regulation}: {checked} of {len(seeds)} provision quotes checked")


@pytest.mark.parametrize(
    ("provision", "label"),
    [
        ("Article 5(2)", "Article 5(2)"),
        ("Article 4", "Article 4"),
        ("Article 9(4), point (e)", "Article 9(4)"),
        ("Article 11(6), first subparagraph, point (a)", "Article 11(6)"),
        ("Article 30(3), point (e)(i)", "Article 30(3)"),
        ("Article 26(5), first subparagraph", "Article 26(5)"),
        ("Principle 1.3(c)(ii)", "Principle 1.3(c)"),
        ("Principle 5.1", "Principle 5.1"),
        ("paragraph 3.8", "Paragraph 3.8"),
    ],
)
def test_unit_label_names_the_unit_that_holds_the_provision(provision, label):
    assert unit_label(provision) == label
