"""Tests that the written policy set quotes SS1/23 only where it says so, word for word.

Three clauses of the fictional bank's set adopt a definition from the Prudential Regulation
Authority's Supervisory Statement SS1/23 and quote it in quotation marks with the statement's
locator. Nothing else in the set may share a run of twelve words with the statement. The statement
is not held in the repository, so these tests read its fetched copy, as the seed provision tests
do: a missing copy fails under ``REQUIRE_REGULATIONS=1`` and is skipped with the reason elsewhere.
"""

import os
import re

import pytest
from policy_support import hmb_policies

from context.regulations import manifest, readers
from context.regulations.fetch import resolve_cache_dir
from context.text import contains_word_for_word

MODEL = "HMB-POL-MRM-004-v2.0"
GOVERNANCE = "HMB-FRM-GOV-000-v2.0"
RUN = 12

# document, clause -> the statement's unit that holds the quoted words, and the locator cited.
QUOTING_CLAUSES = {
    (MODEL, "3.1"): ("Principle 1.1(a)", "1.1(a)"),
    (MODEL, "3.2"): ("Footnote 4", "2.1, footnote 4"),
    (GOVERNANCE, "4.10"): ("Principle 1.1(a)", "1.1(a)"),
}
_QUOTED = re.compile(r'"([^"]+)" \(SS1/23, ([^()]+(?:\([^()]*\))?)\)')


def _statement():
    entry = manifest.load_manifest().get("SS1-23")
    if not (resolve_cache_dir() / entry.cache_file).exists():
        message = (
            "SS1/23 is not held in the repository and its fetched copy is absent; "
            "run python -m context.regulations fetch to check the quotations"
        )
        if os.environ.get("REQUIRE_REGULATIONS"):
            pytest.fail(message)
        pytest.skip(message)
    return readers.read_regulation("SS1-23")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("’", "'"))


def shared_runs(source_words: list[str], text: str, *, length: int = RUN) -> list[int]:
    """Return the length of every run of ``length`` words or more that the text shares.

    Args:
        source_words: The source's words, lower case.
        text: The text to compare.
        length: The shortest run that counts.

    Returns:
        The length of each maximal shared run, in the order the runs occur in the text.
    """
    grams = {tuple(source_words[i : i + length]) for i in range(len(source_words) - length + 1)}
    mine = _words(text)
    runs, i = [], 0
    while i <= len(mine) - length:
        if tuple(mine[i : i + length]) in grams:
            j = i + length
            while j < len(mine) and tuple(mine[j - length + 1 : j + 1]) in grams:
                j += 1
            runs.append(j - i)
            i = j
        else:
            i += 1
    return runs


def _without_quotations(text: str) -> str:
    return _QUOTED.sub("", text)


def test_each_quoting_clause_quotes_the_statement_word_for_word_with_its_locator():
    read = _statement()
    policies = hmb_policies()
    for (document, clause), (unit, locator) in QUOTING_CLAUSES.items():
        text = policies[document].clauses[clause]
        found = _QUOTED.findall(text)
        assert len(found) == 1, f"{document} {clause} quotes the statement {len(found)} times"
        quote, cited = found[0]
        assert cited == locator, f"{document} {clause} cites {cited}, expected {locator}"
        own = [u for u in read.items if u.label == unit]
        assert len(own) == 1, f"the reader has no single unit {unit}"
        assert contains_word_for_word(quote, own[0].text), (
            f"{document} {clause}: the quotation is not word for word in {unit}"
        )
    print(f"{len(QUOTING_CLAUSES)} of {len(QUOTING_CLAUSES)} quoting clauses checked")


def test_the_quotations_are_the_definitions_whole():
    policies = hmb_policies()
    sizes = {
        key: len(_words(_QUOTED.search(policies[key[0]].clauses[key[1]]).group(1)))
        for key in QUOTING_CLAUSES
    }
    assert sizes == {(MODEL, "3.1"): 53, (MODEL, "3.2"): 12, (GOVERNANCE, "4.10"): 23}


def test_no_other_run_of_twelve_words_of_the_statement_is_in_the_policy_set():
    read = _statement()
    source = _words(" ".join(u.text for u in read.items))
    policies = hmb_policies()
    checked = 0
    for document, policy in policies.items():
        for clause, text in policy.clauses.items():
            checked += 1
            outside = _without_quotations(text)
            assert not shared_runs(source, outside), (
                f"{document} clause {clause} shares {RUN} words with SS1/23 outside a quotation"
            )
        assert not shared_runs(source, policy.title), document
    print(f"{checked} clauses of {len(policies)} documents checked")


def test_planted_a_clause_that_copies_twelve_words_of_the_statement_is_caught():
    read = _statement()
    source = _words(" ".join(u.text for u in read.items))
    footnote = next(u.text for u in read.items if u.label == "Footnote 4")
    phrase = footnote.removeprefix("Model use is defined here as ").removesuffix(".")
    bare = f"3.2 The Bank means {phrase}."
    quoted = f'3.2 The Bank means "{phrase}" (SS1/23, 2.1, footnote 4).'
    assert shared_runs(source, _without_quotations(bare)) == [12]
    assert shared_runs(source, _without_quotations(quoted)) == []
