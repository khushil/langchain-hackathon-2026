"""Candidate clauses for each applicable obligation, found by code and logged, kept or dropped.

Four channels find a candidate, none of which loads a model or an embedding:

- ``term``: the clause and the provision share at least three stems whose weight, taken from how
  rare each stem is across the corpus, adds up to ten or more;
- ``defined_term``: a multi-word term that a document defines occurs in both, and the two share
  two more stems beyond the term's own words;
- ``cross_reference``: the clause names an article of the regulation that holds the provision;
- ``graph``: the clause sits next to a clause the other channels found, through the document graph.

A clause of a superseded version is logged and dropped. Every candidate the search reached is
logged: the kept ones, the ones ranked below the limit, the ones below the bar and the ones of a
version no longer in force. An obligation with no kept candidate gets a second look, which lowers
the bar to two stems and adds the clauses that share a rare word of the provision's heading.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from assessment.graph import GraphEdge, defined_terms, edges_of
from assessment.records import Candidate, ClauseRef, FoundBy, Obligation, Register
from assessment.texts import TextIndex
from fsi_common.records import Fact

KEPT_LIMIT = 20
"""The most kept candidates for one obligation, so that a judgement's request stays bounded."""

TERM_BAR = (3, 10.0)
"""Shared stems, and their weight, that make a candidate on terms alone."""

LENIENT_BAR = (2, 6.0)
"""The lower bar a clause must still reach for a defined term or the graph to keep it."""

RELATIVE_BAR = 0.35
"""A term candidate must also weigh at least this share of the heaviest clause for the obligation,
so that a long provision, which shares a little with everything, keeps the clauses that bear on
it and no more."""

SUPPORT_BAR = 0.2
"""The lower share of the heaviest clause that a defined term or the graph needs to keep one."""

HEADING_STEM_WEIGHT = 3.0
"""A heading stem at least this rare marks a clause for the second look."""

_STOP = frozenset(
    "a an the of and or to in on for by with as at is are be been being that this these those it "
    "its from into than which who whom shall should may must can will not no any all each every "
    "other such their there where when under over per also only including include includes more "
    "most less have has had do does done so if then upon within without between through during "
    "before after again further once here both few some own same too very whether they them his "
    "her he she we our us you your".split()
)
_ENDINGS = (
    ("ations", ""),
    ("ation", ""),
    ("ments", ""),
    ("ment", ""),
    ("ities", "ity"),
    ("ity", ""),
    ("ings", ""),
    ("ing", ""),
    ("ies", "y"),
    ("ied", "y"),
    ("ed", ""),
    ("es", ""),
    ("s", ""),
    ("ly", ""),
)
_WORD = re.compile(r"[a-z]{3,}")


def _stem(word: str) -> str:
    for ending, replacement in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[: -len(ending)] + replacement
    return word


def _words(text: str) -> list[tuple[str, str]]:
    return [(_stem(w), w) for w in _WORD.findall(text.lower()) if w not in _STOP]


def stems_of(text: str) -> set[str]:
    """Reduce a text to the stems of its content words.

    Args:
        text: Any text.

    Returns:
        The stems of the words of three letters or more that are not stop words, with plural
        and common endings folded.
    """
    return {stem for stem, _ in _words(text)}


@dataclass(frozen=True)
class _Clause:
    document: str
    number: str
    anchor: str
    bag: frozenset[str]
    in_force: bool


@dataclass(frozen=True)
class _Hit:
    clause: _Clause
    shared: tuple[str, ...]
    weight: float
    channels: tuple[FoundBy, ...]
    detail: tuple[str, ...]


class _Corpus:
    """The corpus read once for the search: each clause's stems, their rarity and the graph."""

    def __init__(self, texts: TextIndex, graph: Sequence[Fact]) -> None:
        self.texts = texts
        self.clauses: list[_Clause] = []
        for document, items in texts.clauses.items():
            title = texts.corpus.document(document)
            title_text = title.entry.title if title else ""
            for clause in items:
                bag = stems_of(f"{clause.text} {clause.heading} {title_text}")
                self.clauses.append(
                    _Clause(
                        document,
                        clause.number,
                        f"clause:{clause.number}",
                        frozenset(bag),
                        texts.in_force(document),
                    )
                )
        frequency = Counter(s for c in self.clauses for s in c.bag)
        total = len(self.clauses)
        self.weight = {s: math.log(1 + total / n) for s, n in frequency.items()}
        self.defined = {
            term: frozenset(stems_of(term))
            for term in defined_terms(texts.clauses)
            if len(stems_of(term)) >= 2
        }
        self.edges: list[GraphEdge] = edges_of(texts, graph)
        self.neighbours: dict[tuple[str, str], set[tuple[str, str]]] = {}
        for edge in self.edges:
            if (
                edge.object_document
                and edge.source_anchor.startswith("clause:")
                and edge.object_anchor.startswith("clause:")
            ):
                a = (edge.source_document, edge.source_anchor)
                b = (edge.object_document, edge.object_anchor)
                self.neighbours.setdefault(a, set()).add(b)
                self.neighbours.setdefault(b, set()).add(a)
        self.structure = {
            key: {n.anchor: n for n in read.structure} for key, read in texts.regulations.items()
        }

        self._units = {
            key: {u.anchor: u for u in read.items} for key, read in texts.regulations.items()
        }

    def heading_of(self, regulation: str, anchor: str) -> str:
        unit = self._units[regulation].get(anchor)
        return unit.heading if unit else ""


def _provision_text(corpus: _Corpus, obligation: Obligation) -> tuple[str, str]:
    heading = corpus.heading_of(obligation.regulation, obligation.anchor)
    titles = [
        corpus.structure[obligation.regulation][p].title
        for p in obligation.parents
        if p in corpus.structure[obligation.regulation]
    ]
    return obligation.provision_words, " ".join([heading, *titles]).strip()


def _cited(corpus: _Corpus, obligation: Obligation) -> dict[tuple[str, str], str]:
    """Clauses that name the article holding the provision, with how they name it."""
    article = obligation.anchor.split("/")[0]
    found: dict[tuple[str, str], str] = {}
    for edge in corpus.edges:
        if edge.object_regulation != obligation.regulation:
            continue
        if edge.object_anchor in (obligation.anchor, article) or (
            edge.object_anchor.split("/")[0] == article and edge.object_anchor.startswith("art:")
        ):
            if article in ("art:1", "art:2", "art:3"):
                continue
            found[(edge.source_document, edge.source_anchor)] = (
                f"cited as {obligation.regulation} {edge.object_anchor}"
            )
    return found


def _surface(text: str) -> dict[str, str]:
    seen: dict[str, str] = {}
    for stem, word in _words(text):
        seen.setdefault(stem, word)
    return seen


def _first_look(
    corpus: _Corpus, obligation: Obligation, *, second_look: bool
) -> tuple[list[_Hit], dict[str, str]]:
    text, heading = _provision_text(corpus, obligation)
    surface = _surface(f"{text} {heading}")
    pstems = frozenset(surface)
    heading_rare = {
        s for s in stems_of(heading) if corpus.weight.get(s, 0.0) >= HEADING_STEM_WEIGHT
    }
    cited = _cited(corpus, obligation)
    terms = [t for t, bag in corpus.defined.items() if bag <= pstems]
    top = max(
        (
            sum(corpus.weight.get(s, 0.0) for s in pstems & c.bag)
            for c in corpus.clauses
            if c.in_force
        ),
        default=0.0,
    )
    base: dict[tuple[str, str], _Hit] = {}
    for clause in corpus.clauses:
        shared = sorted(pstems & clause.bag, key=lambda s: (-corpus.weight.get(s, 0.0), s))
        weight = sum(corpus.weight.get(s, 0.0) for s in shared)
        channels: list[FoundBy] = []
        detail: list[str] = []
        lenient = len(shared) >= LENIENT_BAR[0] and weight >= LENIENT_BAR[1]
        if len(shared) >= TERM_BAR[0] and weight >= max(TERM_BAR[1], RELATIVE_BAR * top):
            channels.append("term")
            detail += [surface[s] for s in shared[:8]]
        hit_terms = [t for t in terms if corpus.defined[t] <= clause.bag]
        if hit_terms:
            own = frozenset().union(*(corpus.defined[t] for t in hit_terms))
            beyond = [s for s in shared if s not in own]
            beyond_weight = sum(corpus.weight.get(s, 0.0) for s in beyond)
            if (
                len(beyond) >= LENIENT_BAR[0]
                and beyond_weight >= LENIENT_BAR[1]
                and weight >= SUPPORT_BAR * top
            ):
                channels.append("defined_term")
                detail += hit_terms
        if (clause.document, clause.anchor) in cited:
            channels.append("cross_reference")
            detail.append(cited[(clause.document, clause.anchor)])
        if (
            second_look
            and not channels
            and (lenient or (heading_rare & clause.bag and len(shared) >= 1))
        ):
            channels.append("term")
            detail += [surface[s] for s in shared[:8]] or sorted(heading_rare & clause.bag)
        if channels or lenient:
            base[(clause.document, clause.number)] = _Hit(
                clause, tuple(surface[s] for s in shared), weight, tuple(channels), tuple(detail)
            )
    strong = {k for k, h in base.items() if h.channels and h.clause.in_force}
    for key, hit in list(base.items()):
        if hit.channels:
            continue
        near = corpus.neighbours.get((key[0], f"clause:{key[1]}"), set())
        if any((d, a.removeprefix("clause:")) in strong for d, a in near):
            if len(hit.shared) >= LENIENT_BAR[0] and hit.weight >= max(
                LENIENT_BAR[1], SUPPORT_BAR * top
            ):
                base[key] = _Hit(hit.clause, hit.shared, hit.weight, ("graph",), hit.shared[:8])
    return list(base.values()), surface


def _to_candidate(
    obligation: Obligation, hit: _Hit, *, kept: bool, reason: str, second_look: bool
) -> Candidate:
    found: list[FoundBy] = list(hit.channels) or ["term"]
    if second_look:
        found.insert(0, "second_look")
    matched = list(dict.fromkeys(m for m in (*hit.detail, *hit.shared[:4]) if m.strip()))
    return Candidate(
        obligation_id=obligation.obligation_id,
        clause=ClauseRef(document=hit.clause.document, clause=hit.clause.number),
        found_by=list(dict.fromkeys(found)),
        matched=matched or ["a shared term"],
        kept=kept,
        reason=reason,
    )


def _rank(hit: _Hit) -> tuple[int, float, str, str]:
    return (
        0 if "cross_reference" in hit.channels else 1,
        -hit.weight,
        hit.clause.document,
        hit.clause.number,
    )


def find_candidates(
    register: Register, texts: TextIndex, graph: Sequence[Fact], *, second_look: bool
) -> list[Candidate]:
    """Find every candidate clause for every applicable obligation of a register.

    Args:
        register: The register; only obligations that apply are searched.
        texts: The regulations and the corpus.
        graph: The document graph's facts.
        second_look: Widen the search: lower the term bar and add the clauses that share a rare
            word of the provision's heading. The engine calls it for the obligations that had
            no kept candidate, in a register that holds only those.

    Returns:
        Every candidate, kept and dropped, in register order, the kept ones first.
    """
    corpus = _Corpus(texts, graph)
    found: list[Candidate] = []
    for obligation in register.obligations:
        if obligation.applies is not True:
            continue
        hits, _ = _first_look(corpus, obligation, second_look=second_look)
        eligible = sorted((h for h in hits if h.channels and h.clause.in_force), key=_rank)
        kept = eligible[:KEPT_LIMIT]
        for hit in kept:
            found.append(
                _to_candidate(
                    obligation,
                    hit,
                    kept=True,
                    second_look=second_look,
                    reason=(
                        f"found by {', '.join(hit.channels)}; {len(hit.shared)} shared terms "
                        f"of weight {hit.weight:.1f}, in a document in force"
                    ),
                )
            )
        for hit in eligible[KEPT_LIMIT:]:
            found.append(
                _to_candidate(
                    obligation,
                    hit,
                    kept=False,
                    second_look=second_look,
                    reason=f"ranked below the {KEPT_LIMIT} kept for this obligation",
                )
            )
        listed = {id(h) for h in eligible}
        for hit in sorted((h for h in hits if id(h) not in listed), key=_rank):
            if not hit.clause.in_force:
                reason = "superseded version, kept as history and never as cover"
            else:
                needed = LENIENT_BAR if second_look else TERM_BAR
                reason = (
                    f"below the bar: {len(hit.shared)} shared terms of weight {hit.weight:.1f}, "
                    f"where {needed[0]} terms of weight {needed[1]:.0f} are needed"
                )
            found.append(
                _to_candidate(obligation, hit, kept=False, second_look=second_look, reason=reason)
            )
    return found


def without_candidates(register: Register, candidates: Iterable[Candidate]) -> list[Obligation]:
    """List the applicable obligations that have no kept candidate.

    Args:
        register: The register.
        candidates: The candidates a look returned.

    Returns:
        The obligations that apply and have none kept, in register order.
    """
    kept = {c.obligation_id for c in candidates if c.kept}
    return [o for o in register.obligations if o.applies is True and o.obligation_id not in kept]
