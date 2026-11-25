"""The texts an assessment is checked against: regulation units and corpus clauses, read whole.

``split_clauses`` is the clause reader the contract fixes: a clause is a line that starts with
its number (``4.1 The Board ...``) under a ``## N. Heading`` line. The engine lane owns this file
after the contract is committed and may add accounting; it keeps these numbers and texts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from context.corpus import CorpusRead, read_corpus
from context.regulations.fetch import Opener, urllib_opener
from context.regulations.manifest import load_manifest
from context.regulations.model import RegulationRead
from context.regulations.readers import read_regulation
from context.text import contains_word_for_word
from fsi_common.records import Source

_HEADING = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$")
_CLAUSE = re.compile(r"^(\d+(?:\.\d+)+)\s+(\S.*)$")
_STATUS = re.compile(r"^Status:\s*(.+?)\s*$", re.MULTILINE)
_CONTROL = re.compile(r"^([A-Z][A-Za-z ]+):\s*(\S.*)$")


@dataclass(frozen=True)
class Clause:
    """One numbered clause of a document, with the heading of the section it sits in."""

    number: str
    heading: str
    text: str


def split_clauses(text: str) -> list[Clause]:
    """Split a policy document's markdown into its numbered clauses, in order.

    Args:
        text: The document's text.

    Returns:
        Every line that starts with a clause number, with its section heading; empty when the
        document has none.
    """
    heading = ""
    clauses = []
    for line in text.splitlines():
        if found := _HEADING.match(line):
            heading = found.group(2)
        elif found := _CLAUSE.match(line.strip()):
            clauses.append(Clause(number=found.group(1), heading=heading, text=found.group(2)))
    return clauses


@dataclass(frozen=True)
class TextIndex:
    """The regulations and one corpus, read whole, with the lookups the validators need."""

    corpus: CorpusRead
    regulations: dict[str, RegulationRead]
    clauses: dict[str, list[Clause]]
    status: dict[str, str]
    _clause_text: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)
    _control: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)
    _by_source: dict[str, tuple[str, str]] = field(default_factory=dict, repr=False)

    def text_at(self, source_id: str, anchor: str) -> str | None:
        """Return the text at a place, whichever source it is in.

        A regulation's place is a unit anchor; a document's is ``clause:N.M`` or
        ``control:<field>``, a line of its document control block, for example
        ``control:supersedes``.

        Args:
            source_id: The source record's id.
            anchor: The place.

        Returns:
            The text, or None when the source or the place is unknown.
        """
        kind, name = self._by_source.get(source_id, ("", ""))
        if kind == "regulation":
            read = self.regulations[name]
            return next((u.text for u in read.items if u.anchor == anchor), None)
        if kind == "document":
            prefix, _, rest = anchor.partition(":")
            if prefix == "clause":
                return self.clause_text(name, rest)
            if prefix == "control":
                return self._control.get((name, rest))
        return None

    def quote_at(self, source_id: str, anchor: str, quote: str) -> bool:
        """Say whether a quote lies word for word at a place.

        Args:
            source_id: The source record's id.
            anchor: The place.
            quote: The quote.

        Returns:
            True when the place exists and holds the quote.
        """
        return contains_word_for_word(quote, self.text_at(source_id, anchor))

    def regulation_source(self, regulation: str) -> Source:
        """Return the source record of a regulation.

        Args:
            regulation: Its key.

        Returns:
            Its source.
        """
        return self.regulations[regulation].source

    def source(self, document: str) -> Source:
        """Return the source record of a corpus document.

        Args:
            document: The document's id.

        Returns:
            Its source.

        Raises:
            KeyError: If the corpus has no such document.
        """
        found = self.corpus.document(document)
        if found is None:
            raise KeyError(f"The corpus has no document {document}.")
        return found.source

    def clause_text(self, document: str, clause: str) -> str | None:
        """Return a clause's text, or None when the document has no such clause.

        Args:
            document: The document's id.
            clause: The clause number.

        Returns:
            The text, or None.
        """
        return self._clause_text.get((document, clause))

    def in_force(self, document: str) -> bool:
        """Say whether a document's own control block gives it as in force.

        Args:
            document: The document's id.

        Returns:
            True when its status line reads "In force".
        """
        return self.status.get(document, "").lower() == "in force"

    def clause_count(self, *, in_force_only: bool = False) -> int:
        """Count the clauses of the corpus.

        Args:
            in_force_only: Count only the documents in force.

        Returns:
            The count.
        """
        return sum(len(c) for d, c in self.clauses.items() if not in_force_only or self.in_force(d))

    def unit_count(self, regulation: str) -> int:
        """Count the units of a regulation.

        Args:
            regulation: Its key.

        Returns:
            The count.
        """
        return len(self.regulations[regulation].items)

    def has_place(self, regulation: str, place: str) -> bool:
        """Say whether a regulation has a unit or a heading by that anchor.

        Args:
            regulation: Its key.
            place: A unit anchor or a structure anchor.

        Returns:
            True when either exists.
        """
        read = self.regulations[regulation]
        return any(u.anchor == place for u in read.items) or any(
            n.anchor == place for n in read.structure
        )

    def provision_has(self, regulation: str, anchor: str, quote: str) -> bool:
        """Say whether a quote lies word for word in a regulation unit.

        Args:
            regulation: Its key.
            anchor: The unit's anchor.
            quote: The quote.

        Returns:
            True when the unit exists and holds the quote at word boundaries.
        """
        try:
            text = self.regulations[regulation].text(anchor)
        except KeyError:
            return False
        return contains_word_for_word(quote, text)

    def clause_has(self, document: str, clause: str, quote: str) -> bool:
        """Say whether a quote lies word for word in a clause.

        Args:
            document: The document's id.
            clause: The clause number.
            quote: The quote.

        Returns:
            True when the clause exists and holds the quote at word boundaries.
        """
        return contains_word_for_word(quote, self.clause_text(document, clause))


def load_texts(
    corpus: str, *, cache_dir: Path | None = None, opener: Opener = urllib_opener
) -> TextIndex:
    """Read every regulation of the manifest and every document of a corpus.

    Args:
        corpus: The corpus's name.
        cache_dir: Where closed texts are cached; ``REGULATIONS_CACHE_DIR`` by default.
        opener: What fetches a closed text that is not cached; tests give one that refuses.

    Returns:
        The index.

    Raises:
        context.errors.ContextError: Any error of the regulation or corpus readers, unchanged.
    """
    regulations = {
        entry.key: read_regulation(entry.key, cache_dir=cache_dir, opener=opener)
        for entry in load_manifest().regulations
    }
    read = read_corpus(corpus)
    clauses: dict[str, list[Clause]] = {}
    status: dict[str, str] = {}
    texts: dict[tuple[str, str], str] = {}
    control: dict[tuple[str, str], str] = {}
    by_source = {r.source.id: ("regulation", k) for k, r in regulations.items()}
    for document in read.documents:
        by_source[document.source.id] = ("document", document.entry.id)
        for line in (document.text or "").split("\n## 1.")[0].splitlines():
            if found := _CONTROL.match(line.strip()):
                control[(document.entry.id, found.group(1).lower().replace(" ", "_"))] = (
                    line.strip()
                )
        text = document.text or ""
        clauses[document.entry.id] = split_clauses(text)
        found = _STATUS.search(text)
        status[document.entry.id] = found.group(1) if found else ""
        for clause in clauses[document.entry.id]:
            texts[(document.entry.id, clause.number)] = clause.text
    return TextIndex(
        corpus=read,
        regulations=regulations,
        clauses=clauses,
        status=status,
        _clause_text=texts,
        _control=control,
        _by_source=by_source,
    )
