"""Tests that the written policy set quotes SS1/23 only where it says so, word for word.

Three clauses of the fictional bank's set adopt a definition from the Prudential Regulation
Authority's Supervisory Statement SS1/23 and quote it in quotation marks with the statement's
locator. Nothing else in the set may share a run of twelve words with the statement, and no other
clause may carry an attribution to it: the scan reads every clause outside those three quotations,
and every title, section heading and document control line whole. The statement
is not held in the repository, so these tests read its fetched copy, as the seed provision tests
do: a missing copy fails under ``REQUIRE_REGULATIONS=1`` and is skipped with the reason elsewhere.
"""

import os
import re

import pytest
from policy_support import PolicyText, hmb_policies

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
ATTRIBUTION = "(SS1/23,"
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


def _outside_quotations(document: str, clause: str, text: str) -> str:
    """Return a clause's text with its attributed quotation taken out, where it may have one.

    Only the three clauses of ``QUOTING_CLAUSES`` are allowed a quotation of the statement, and
    each exactly one. Any other clause that carries an attribution to the statement is refused,
    so a new quotation elsewhere cannot hide from the scan behind its own marks.

    Args:
        document: The document's manifest id.
        clause: The clause number.
        text: The clause's text.

    Returns:
        The text a reader sees outside the allowed quotation; the whole text for other clauses.

    Raises:
        AssertionError: If a clause outside ``QUOTING_CLAUSES`` carries an attribution to the
            statement, or a quoting clause carries other than one quotation.
    """
    if (document, clause) in QUOTING_CLAUSES:
        found = _QUOTED.findall(text)
        assert len(found) == 1, f"{document} {clause} quotes the statement {len(found)} times"
        return _QUOTED.sub("", text)
    assert ATTRIBUTION not in text, (
        f"{document} clause {clause} carries an attribution to SS1/23 and is not a quoting clause"
    )
    return text


def scanned_texts(document: str, policy: PolicyText) -> list[tuple[str, str]]:
    """Return every piece of a policy the twelve-word search reads, with where it stands.

    Args:
        document: The document's manifest id.
        policy: The document as the tests read it.

    Returns:
        The title, each section heading as written, each document control line as written, and
        each clause outside its allowed quotation, each with a label for a failure message.
    """
    texts = [(f"{document} title", policy.title)]
    texts += [(f"{document} heading {n}", f"{n}. {heading}") for n, heading in policy.sections]
    texts += [(f"{document} control line {k}", f"{k}: {v}") for k, v in policy.control.items()]
    texts += [
        (f"{document} clause {number}", _outside_quotations(document, number, text))
        for number, text in policy.clauses.items()
    ]
    return texts


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
        for where, text in scanned_texts(document, policy):
            checked += 1
            assert not shared_runs(source, text), (
                f"{where} shares {RUN} words with SS1/23 outside a quotation"
            )
    print(f"{checked} texts of {len(policies)} documents checked")


def _footnote_phrase(read) -> str:
    footnote = next(u.text for u in read.items if u.label == "Footnote 4")
    return footnote.removeprefix("Model use is defined here as ").removesuffix(".")


def test_planted_a_clause_that_copies_twelve_words_of_the_statement_is_caught():
    read = _statement()
    source = _words(" ".join(u.text for u in read.items))
    phrase = _footnote_phrase(read)
    bare = f"3.2 The Bank means {phrase}."
    quoted = f'3.2 The Bank means "{phrase}" (SS1/23, 2.1, footnote 4).'
    assert shared_runs(source, _outside_quotations(MODEL, "9.9", bare)) == [12]
    assert shared_runs(source, _outside_quotations(MODEL, "3.2", quoted)) == []
    with pytest.raises(AssertionError, match="quotes the statement 0 times"):
        _outside_quotations(MODEL, "3.2", bare)


def test_planted_an_attributed_quotation_in_another_clause_is_refused():
    read = _statement()
    phrase = _footnote_phrase(read)
    text = f'The Bank adopts "{phrase}" (SS1/23, 2.1, footnote 4).'
    with pytest.raises(AssertionError, match="not a quoting clause"):
        _outside_quotations(MODEL, "9.9", text)
    with pytest.raises(AssertionError, match="not a quoting clause"):
        _outside_quotations(MODEL, "3.3", text)


def test_planted_a_heading_or_control_line_taken_from_the_statement_is_caught():
    read = _statement()
    source = _words(" ".join(u.text for u in read.items))
    words = _words(" ".join(u.text for u in read.items if u.label == "Footnote 4"))
    heading = " ".join(words[:13])
    planted = PolicyText(
        title="A title",
        control={"Owner": heading},
        sections=[("9", heading)],
        clauses={"9.1": "The Bank keeps this section short."},
    )
    flagged = [where for where, text in scanned_texts(MODEL, planted) if shared_runs(source, text)]
    assert flagged == [f"{MODEL} heading 9", f"{MODEL} control line Owner"]
