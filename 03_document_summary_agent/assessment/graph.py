"""The document graph, found by code: five relations, each fact quoting both of its ends.

A graph fact is a ``Fact`` whose kind is ``implements``, ``refers_to``, ``supersedes``,
``defines`` or ``delegates``. Its subject and quote are one end; the attributes
``object_source_id``, ``object_anchor`` and ``object_quote`` are the other. Every edge is read
from the words of the documents: a reference to another document's reference, a control line, a
definition, a clause that names an article of a regulation. A reference to a document the corpus
does not hold makes no edge, because there is no text to quote at its far end.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass

from assessment.bundle import FACT_CONTEXT
from assessment.records import Relation
from assessment.texts import Clause, TextIndex
from fsi_common.records import (
    CheckResult,
    ClaimStatus,
    Extractor,
    Fact,
    Provenance,
    SourceRef,
)

EXTRACTOR = Extractor(name="assessment-engine", version="1.0.0")
QUOTE_CHECK = "quote-verbatim.v1"

_REFERENCE = re.compile(r"\bHMB-[A-Z]+-[A-Z]+-\d+\b")
_REGULATION_NAMES = {"2022/2554": "DORA", "2024/1689": "AI-ACT"}
_REGULATION_MENTION = re.compile(r"Regulation \(EU\) (2022/2554|2024/1689)|\bSS1/23\b")
_ARTICLE_BEFORE = re.compile(r"Article (\d+)(?:\((\d+)\))? of (?:the )?$")
_PLACE_BEFORE = re.compile(r"(?:clause (\d+\.\d+)|section (\d+)) of (?:the )?[^()]{0,90}$")
_DEFINITION = re.compile(r'^"([^"]{2,60})" means\b')
_IMPLEMENTS = re.compile(r"\b(implements?|intended to meet|requires?)\b")
_DELEGATION = re.compile(r"delegation in section (\d+) of the [^()]*\((HMB-[A-Z]+-[A-Z]+-\d+)\)")
_SUPERSEDES = re.compile(r"^Supersedes:\s*(HMB-[A-Z]+-[A-Z]+-\d+) version (\S+)")


@dataclass(frozen=True)
class GraphEdge:
    """One edge of the graph, read back from its fact: both ends as a place in a source."""

    relation: Relation
    source_document: str
    source_anchor: str
    object_document: str | None
    object_regulation: str | None
    object_anchor: str
    term: str | None


def lead(text: str, words: int = 14) -> str:
    """Return the first words of a text, joined by single spaces.

    Args:
        text: The text.
        words: How many words to keep.

    Returns:
        The words, which lie word for word in the text.
    """
    return " ".join(text.split()[:words])


def digest_of(texts: TextIndex, source_id: str) -> str:
    """Return the digest of a source, a regulation's or a document's.

    Args:
        texts: The texts.
        source_id: The source record's id.

    Returns:
        The digest the source record carries.
    """
    for read in texts.regulations.values():
        if read.source.id == source_id:
            return read.source.digest
    return next(d.source.digest for d in texts.corpus.documents if d.source.id == source_id)


def make_fact(
    texts: TextIndex, *, kind: str, source_id: str, anchor: str, quote: str, **attrs: str
) -> Fact:
    """Build one fact whose quote the plain-code check has found word for word at its place.

    Args:
        texts: The texts the quote is taken from.
        kind: The fact's kind, one of the dataset's closed list.
        source_id: The source record's id.
        anchor: The place in the source.
        quote: The quote.
        **attrs: The fact's attributes.

    Returns:
        The fact.

    Raises:
        ValueError: If the quote does not lie word for word at the place.
    """
    if not texts.quote_at(source_id, anchor, quote):
        raise ValueError(f"The quote is not word for word at {source_id} {anchor}: {quote[:60]!r}")
    return Fact.build(
        context=FACT_CONTEXT,
        kind=kind,
        subject=SourceRef(source_id=source_id, anchor=anchor),
        quote=quote,
        attributes=dict(attrs),
        status=ClaimStatus(status="documented"),
        provenance=Provenance(
            source_id=source_id,
            anchor=anchor,
            extractor=EXTRACTOR,
            as_of=digest_of(texts, source_id),
        ),
        checks=[
            CheckResult(
                check=QUOTE_CHECK,
                outcome="pass",
                detail=f"the quote lies word for word at {anchor}",
            )
        ],
    )


def resolve_reference(texts: TextIndex, reference: str, *, from_document: str) -> str | None:
    """Find the document a reference such as ``HMB-POL-ICT-001`` names.

    Args:
        texts: The texts.
        reference: The reference, without a version.
        from_document: The document that names it; a document is never its own target.

    Returns:
        The id of the document, the version in force when there are several; None when the
        corpus holds no document with that reference, or only the citing document itself.
    """
    wanted = f"Reference: {reference}"
    found = [
        d for d in texts.clauses if texts.control(d, "reference") == wanted and d != from_document
    ]
    if not found:
        return None
    return next((d for d in found if texts.in_force(d)), found[0])


def defined_terms(
    clauses: Mapping[str, Sequence[Clause]], *, in_force: Collection[str] | None = None
) -> dict[str, tuple[str, str]]:
    """Find the terms the documents define, each where it is first defined.

    Args:
        clauses: Each document's clauses, by document id.
        in_force: The documents in force. A definition in one of them is preferred to an earlier
            one in a document that is not; all documents count alike when not given.

    Returns:
        Each quoted term that a clause opens with (``"Term" means``), with the document and the
        clause number of its first definition, taking those in force first.
    """
    found: dict[str, tuple[str, str]] = {}
    documents = (
        list(clauses) if in_force is None else sorted(clauses, key=lambda d: d not in in_force)
    )
    for document in documents:
        for clause in clauses[document]:
            match = _DEFINITION.match(clause.text)
            if match and match.group(1) not in found:
                found[match.group(1)] = (document, clause.number)
    return found


def _section_clause(texts: TextIndex, document: str, section: str) -> str | None:
    clause = next((c for c in texts.clauses[document] if c.number.split(".")[0] == section), None)
    return f"clause:{clause.number}" if clause else None


def _place_in(texts: TextIndex, document: str, before: str) -> str | None:
    """Name the clause a phrase such as ``clause 4.5 of the`` or ``section 11 of the`` points at."""
    found = _PLACE_BEFORE.search(before.rstrip(" ("))
    if not found:
        return None
    if found.group(1):
        return f"clause:{found.group(1)}" if texts.clause_text(document, found.group(1)) else None
    return _section_clause(texts, document, found.group(2))


def _clause_fact(
    texts: TextIndex,
    relation: Relation,
    document: str,
    clause: Clause,
    obj: tuple[str, str, str],
    **attrs: str,
) -> Fact:
    source_id = texts.source(document).id
    return make_fact(
        texts,
        kind=relation,
        source_id=source_id,
        anchor=f"clause:{clause.number}",
        quote=lead(clause.text),
        object_source_id=obj[0],
        object_anchor=obj[1],
        object_quote=obj[2],
        **attrs,
    )


def _document_edges(texts: TextIndex) -> list[Fact]:
    facts: list[Fact] = []
    for document, clauses in texts.clauses.items():
        for clause in clauses:
            for found in _REFERENCE.finditer(clause.text):
                target = resolve_reference(texts, found.group(0), from_document=document)
                if target is None:
                    continue
                anchor = _place_in(texts, target, clause.text[: found.start()])
                relation: Relation = (
                    "implements"
                    if re.search(r"\bimplements\b", clause.text[: found.start()])
                    else "refers_to"
                )
                if anchor is None:
                    anchor = "control:reference"
                    quote = texts.control(target, "reference") or ""
                else:
                    quote = lead(texts.clause_text(target, anchor.split(":")[1]) or "")
                facts.append(
                    _clause_fact(
                        texts, relation, document, clause, (texts.source(target).id, anchor, quote)
                    )
                )
    return facts


def _regulation_unit(texts: TextIndex, regulation: str, article: str | None, para: str | None):
    if regulation not in texts.regulations:
        return None
    items = texts.regulations[regulation].items
    by_anchor = {u.anchor: u for u in items}
    if article:
        for anchor in (
            f"art:{article}/{para}" if para else "",
            f"art:{article}",
            f"art:{article}/1",
        ):
            if anchor in by_anchor:
                return by_anchor[anchor]
    if regulation == "SS1-23":
        return by_anchor.get("para:1.1")
    return by_anchor.get("art:1/1") or by_anchor.get("art:1")


def _regulation_edges(texts: TextIndex) -> list[Fact]:
    facts: list[Fact] = []
    for document, clauses in texts.clauses.items():
        for clause in clauses:
            for found in _REGULATION_MENTION.finditer(clause.text):
                key = _REGULATION_NAMES.get(found.group(1) or "", "SS1-23")
                article = _ARTICLE_BEFORE.search(clause.text[: found.start()])
                unit = _regulation_unit(
                    texts,
                    key,
                    article.group(1) if article else None,
                    article.group(2) if article else None,
                )
                if unit is None:
                    continue
                relation: Relation = (
                    "implements" if not article and _IMPLEMENTS.search(clause.text) else "refers_to"
                )
                facts.append(
                    _clause_fact(
                        texts,
                        relation,
                        document,
                        clause,
                        (texts.regulation_source(key).id, unit.anchor, lead(unit.text)),
                    )
                )
    return facts


def _control_edge(
    texts: TextIndex, relation: Relation, document: str, field_name: str, obj: tuple[str, str, str]
) -> Fact:
    return make_fact(
        texts,
        kind=relation,
        source_id=texts.source(document).id,
        anchor=f"control:{field_name}",
        quote=texts.control(document, field_name) or "",
        object_source_id=obj[0],
        object_anchor=obj[1],
        object_quote=obj[2],
    )


def _supersession_edges(texts: TextIndex) -> list[Fact]:
    facts: list[Fact] = []
    for document in texts.clauses:
        found = _SUPERSEDES.match(texts.control(document, "supersedes") or "")
        if not found:
            continue
        reference, version = found.groups()
        old = next(
            (
                d
                for d in texts.clauses
                if d != document
                and texts.control(d, "reference") == f"Reference: {reference}"
                and texts.control(d, "version") == f"Version: {version}"
            ),
            None,
        )
        if old is None:
            continue
        field_name = "superseded_by" if texts.control(old, "superseded_by") else "version"
        quote = texts.control(old, field_name) or ""
        facts.append(
            _control_edge(
                texts,
                "supersedes",
                document,
                "supersedes",
                (texts.source(old).id, f"control:{field_name}", quote),
            )
        )
    return facts


def _delegation_edges(texts: TextIndex) -> list[Fact]:
    facts: list[Fact] = []
    for document in texts.clauses:
        approved = texts.control(document, "approved_by") or ""
        found = _DELEGATION.search(approved)
        kind = (
            (texts.control(document, "document_type") or "").removeprefix("Document type:").strip()
        )
        if not found or not kind:
            continue
        framework = resolve_reference(texts, found.group(2), from_document=document)
        if framework is None:
            continue
        plural = f"{kind.lower()}s"
        clause = next(
            (
                c
                for c in texts.clauses[framework]
                if c.number.split(".")[0] == found.group(1)
                and plural in c.text.lower()
                and "deleg" in c.text.lower()
            ),
            None,
        )
        if clause is None:
            continue
        facts.append(
            _clause_fact(
                texts,
                "delegates",
                framework,
                clause,
                (texts.source(document).id, "control:approved_by", approved),
            )
        )
    return facts


def _use_of(term: str, text: str) -> int | None:
    """Return where a defined term is used in a text, or None; a longer name does not count."""
    for found in re.finditer(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text):
        after = text[found.end() :]
        if " " not in term and re.match(r" [A-Z]", after):
            continue
        return found.start()
    return None


def _definition_edges(texts: TextIndex) -> list[Fact]:
    facts: list[Fact] = []
    for term, (home, number) in defined_terms(texts.clauses).items():
        defining = next(c for c in texts.clauses[home] if c.number == number)
        for document, clauses in texts.clauses.items():
            if document == home:
                continue
            for clause in clauses:
                at = _use_of(term, clause.text)
                if at is None:
                    continue
                words = clause.text[at:].split()[:10]
                facts.append(
                    _clause_fact(
                        texts,
                        "defines",
                        home,
                        defining,
                        (texts.source(document).id, f"clause:{clause.number}", " ".join(words)),
                        term=term,
                    )
                )
                break
    return facts


def build_graph(texts: TextIndex) -> list[Fact]:
    """Find every edge of the document graph by code.

    Args:
        texts: The regulations and the corpus, read whole.

    Returns:
        The facts, one per edge, in the order: references between documents, references to
        regulations, supersessions, delegations, definitions; duplicates by id removed.
    """
    parts = [
        _document_edges(texts),
        _regulation_edges(texts),
        _supersession_edges(texts),
        _delegation_edges(texts),
        _definition_edges(texts),
    ]
    unique: dict[str, Fact] = {}
    for fact in (f for part in parts for f in part):
        unique.setdefault(fact.id, fact)
    return list(unique.values())


def edges_of(texts: TextIndex, facts: Iterable[Fact]) -> list[GraphEdge]:
    """Read graph facts back into edges, each end placed in its document or regulation.

    Args:
        texts: The texts the facts were built on.
        facts: Facts of any kind; those that are not graph facts are skipped.

    Returns:
        One edge per graph fact.
    """
    edges: list[GraphEdge] = []
    for fact in facts:
        if fact.kind not in ("implements", "refers_to", "supersedes", "defines", "delegates"):
            continue
        source = texts.locate(fact.subject.source_id)
        target = texts.locate(str(fact.attributes["object_source_id"]))
        if source is None or target is None or source[0] != "document":
            continue
        edges.append(
            GraphEdge(
                relation=fact.kind,  # type: ignore[arg-type]
                source_document=source[1],
                source_anchor=fact.subject.anchor,
                object_document=target[1] if target[0] == "document" else None,
                object_regulation=target[1] if target[0] == "regulation" else None,
                object_anchor=str(fact.attributes["object_anchor"]),
                term=str(fact.attributes["term"]) if "term" in fact.attributes else None,
            )
        )
    return edges
