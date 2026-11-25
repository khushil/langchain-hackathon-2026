"""The lines a run prints: its counts and the three measures of the seeded cases, by regulation.

The deck reads these lines and nothing else, so each is written in the form the deck's generator
looks for. A measure counts over a population the line states.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from assessment.engine import REGULATION_NAMES
from assessment.records import RELATIONS, Bundle, SeedMatch
from assessment.texts import TextIndex

_DIGIT = re.compile(r"\d")


def _populations(
    matches: list[SeedMatch],
    keep: Callable[[SeedMatch], bool],
    hit: Callable[[SeedMatch], bool],
    included: Sequence[str],
) -> list[tuple[str, int, int]]:
    rows = []
    for key, name in (*((k, REGULATION_NAMES[k]) for k in included), ("all", "all")):
        group = [m for m in matches if keep(m) and (key == "all" or m.regulation == key)]
        rows.append((name, sum(hit(m) for m in group), len(group)))
    return rows


def _wrong_citation(m: SeedMatch) -> bool:
    cited = {(c.document, c.clause) for c in m.cited_clauses}
    seeded = {(c.document, c.clause) for c in m.seeded_clauses}
    return not cited & seeded


def _example(bundle: Bundle) -> str | None:
    register = bundle.obligation_register
    seeds = {
        m.obligation_ids[0]: m.seed_id for m in bundle.seed_matches if len(m.obligation_ids) == 1
    }
    for a in bundle.assessments:
        if a.state not in ("not covered", "partly covered") or not a.clause_quotes:
            continue
        quote = a.clause_quotes[0]
        text = f"{a.provision_quote} {quote.quote}"
        obligation = register.obligation(a.obligation_id)
        if _DIGIT.search(text) or "|" in text or obligation is None:
            continue
        where = f"{quote.clause.document} clause {quote.clause.clause}"
        return (
            f"Example assessment: {seeds.get(a.obligation_id, a.obligation_id)} | "
            f"{obligation.label} | {a.state} | {a.provision_quote} | {where} | {quote.quote}"
        )
    return None


def left_out_lines(texts: TextIndex) -> list[str]:
    """Say which regulations a run does not include; no line when it includes all of them.

    Args:
        texts: The texts the run read.

    Returns:
        One line naming the regulations left out, or none.
    """
    left = [REGULATION_NAMES[k] for k in REGULATION_NAMES if k not in texts.regulations]
    return [f"Regulations not included: {', '.join(left)}"] if left else []


def run_lines(bundle: Bundle, texts: TextIndex) -> list[str]:
    """Write the lines of a finished run.

    Args:
        bundle: The run's bundle.
        texts: The corpus, for the number of documents.

    Returns:
        The graph, register and assessment counts, the three measures by regulation and for all,
        and one example assessment when one has quotes without a digit.
    """
    register = bundle.obligation_register
    states = [a.state for a in bundle.assessments]
    included = [k for k in REGULATION_NAMES if k in texts.regulations]
    lines = left_out_lines(texts)
    lines += [
        f"Document graph: {len(texts.corpus.documents)} documents, "
        f"{sum(f.kind in RELATIONS for f in bundle.facts)} links",
        f"Obligation register: {len(register.obligations)} obligations, "
        f"{sum(o.applies is True for o in register.obligations)} apply to the firm",
        f"Assessments: {len(states)} applicable obligations assessed: "
        f"{states.count('covered')} covered, {states.count('partly covered')} partly covered, "
        f"{states.count('not covered')} not covered, {states.count('in conflict')} in conflict",
    ]
    matches = bundle.seed_matches
    for name, found, total in _populations(
        matches,
        lambda m: m.seeded_state != "covered",
        lambda m: m.found_state != "covered",
        included,
    ):
        lines.append(f"seeded_gaps_found [{name}]: {found} of {total} seeded gaps")
    for name, found, total in _populations(
        matches,
        lambda m: m.seeded_state == "covered",
        lambda m: m.found_state != "covered",
        included,
    ):
        lines.append(f"false_gaps [{name}]: {found} of {total} seeds the labels hold as covered")
    for name, wrong, total in _populations(
        matches,
        lambda m: bool(m.seeded_clauses) and m.found_state != "not covered",
        _wrong_citation,
        included,
    ):
        lines.append(
            f"wrong_citations [{name}]: {wrong} of {total} seeds that name clauses and were found "
            "as anything but not covered"
        )
    example = _example(bundle)
    if example:
        lines.append(example)
    return lines
