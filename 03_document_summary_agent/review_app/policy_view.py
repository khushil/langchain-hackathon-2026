"""What the policy pages show: the picture, the register, one assessment, the clauses, the graph.

Everything here reads a ``Bundle`` and the corpus's documents and returns plain records for the
templates. Nothing here decides anything: a decision and a sign-off are built by the review route
alone. The words say what the documents state against a provision, and never that a firm complies.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from assessment.records import (
    RELATIONS,
    STATES,
    Assessment,
    Bundle,
    Candidate,
    ClauseQuote,
    Obligation,
    PointJudgement,
    State,
)

from context.corpus import read_corpus
from fsi_common.app import Answer, Cell, Column, Tile
from fsi_common.app.pages import TableView, build_table
from fsi_common.records import CheckResult, Decision, Fact, Person, Statement
from review_app.source_view import Segment, mark_quote

PREFIX = "/compliance-brief/policies"
REGULATION_NAMES = {"DORA": "DORA", "AI-ACT": "AI Act", "SS1-23": "SS1/23"}
LEADING_REGULATION = {"harbour-mutual-bank": "DORA"}
"""The regulation that leads the picture for a corpus: the one the firm's documents answer first."""
STATE_WORDS: dict[State | None, str] = {
    "covered": "Covered",
    "partly covered": "Partly covered",
    "not covered": "Not covered",
    "in conflict": "In conflict",
    None: "Not assessed",
}
STATE_KIND: dict[State | None, str] = {
    "covered": "covered",
    "partly covered": "partly",
    "not covered": "not",
    "in conflict": "conflict",
    None: "none",
}
GAP_STATES: tuple[State, ...] = ("partly covered", "not covered", "in conflict")
RELATION_WORDS = {
    "implements": "implements",
    "refers_to": "refers to",
    "supersedes": "supersedes",
    "defines": "defines a term used in",
    "delegates": "delegates to",
}
FOUND_BY_WORDS = {
    "term": "shared terms",
    "defined_term": "a defined term",
    "cross_reference": "a cross reference",
    "graph": "the document graph",
    "second_look": "the second look",
}
_STATUS = re.compile(r"^Status:\s*(.+?)\s*$", re.MULTILINE)
_CLAUSE = re.compile(r"^(\d+(?:\.\d+)+)\s+(\S.*)$")
_HEADING = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$")
_VERSION = re.compile(r"-v(\d+(?:\.\d+)*)$")


class PolicyViewError(LookupError):
    """A page asked for something the bundle or the corpus does not hold."""


@dataclass(frozen=True)
class ClauseLine:
    """One numbered clause of a document."""

    number: str
    heading: str
    text: str


@dataclass(frozen=True)
class PolicyDocument:
    """One document of the corpus as the pages name it."""

    doc_id: str
    title: str
    version: str
    status: str
    source_id: str
    clauses: tuple[ClauseLine, ...]

    @property
    def in_force(self) -> bool:
        """Whether the document's own control block gives it as in force."""
        return self.status.lower() == "in force"

    @property
    def label(self) -> str:
        """The title with its version, for a heading."""
        return f"{self.title}, version {self.version}" if self.version else self.title

    def clause(self, number: str) -> ClauseLine | None:
        """Return a clause by number, or None."""
        return next((c for c in self.clauses if c.number == number), None)


def _clauses(text: str) -> tuple[ClauseLine, ...]:
    heading = ""
    found: list[ClauseLine] = []
    for line in text.splitlines():
        if match := _HEADING.match(line):
            heading = match.group(2)
        elif match := _CLAUSE.match(line.strip()):
            found.append(ClauseLine(match.group(1), heading, match.group(2)))
    return tuple(found)


def read_documents(corpus: str) -> tuple[PolicyDocument, ...]:
    """Read every document of a corpus with its clauses, in manifest order.

    Args:
        corpus: The corpus's name.

    Returns:
        The documents.

    Raises:
        context.errors.ContextError: Any error of the corpus reader, unchanged.
    """
    documents = []
    for document in read_corpus(corpus).documents:
        text = document.text or ""
        status = _STATUS.search(text)
        version = _VERSION.search(document.entry.id)
        documents.append(
            PolicyDocument(
                doc_id=document.entry.id,
                title=document.entry.title,
                version=version.group(1) if version else "",
                status=status.group(1) if status else "",
                source_id=document.source.id,
                clauses=_clauses(text),
            )
        )
    return tuple(documents)


@dataclass(frozen=True)
class PolicyData:
    """A bundle with the documents it was made from, indexed for the pages."""

    bundle: Bundle
    documents: tuple[PolicyDocument, ...]
    assessments: Mapping[str, Assessment] = field(init=False)
    obligations: Mapping[str, Obligation] = field(init=False)
    facts: Mapping[str, Fact] = field(init=False)

    def __post_init__(self) -> None:
        register = self.bundle.obligation_register
        object.__setattr__(
            self, "assessments", {a.obligation_id: a for a in self.bundle.assessments}
        )
        object.__setattr__(self, "obligations", {o.obligation_id: o for o in register.obligations})
        object.__setattr__(self, "facts", {f.id: f for f in self.bundle.facts})

    @property
    def corpus(self) -> str:
        """The corpus's name."""
        return self.bundle.index.corpus

    @property
    def name(self) -> str:
        """The firm's name as the pages say it."""
        return self.corpus.replace("-", " ").title()

    @property
    def in_force(self) -> tuple[PolicyDocument, ...]:
        """The documents in force, which are the picture's columns."""
        return tuple(d for d in self.documents if d.in_force)

    def document(self, doc_id: str) -> PolicyDocument | None:
        """Return a document by id, or None."""
        return next((d for d in self.documents if d.doc_id == doc_id), None)

    @property
    def regulations(self) -> tuple[str, ...]:
        """The regulations of the register, the corpus's leading one first."""
        keys = [p.regulation for p in self.bundle.obligation_register.populations]
        lead = LEADING_REGULATION.get(self.corpus)
        return tuple(sorted(keys, key=lambda k: (k != lead, keys.index(k))))

    def applicable(self, regulation: str | None = None) -> list[Obligation]:
        """Return the obligations that apply, in register order."""
        return [
            o
            for o in self.bundle.obligation_register.obligations
            if o.applies is True and (regulation is None or o.regulation == regulation)
        ]

    def source_names(self) -> dict[str, str]:
        """Name each source the bundle's facts rest on: a document by title, a regulation by key."""
        names = {d.source_id: d.label for d in self.documents}
        for fact in self.bundle.facts:
            if fact.kind == "provision" and "obligation_id" in fact.attributes:
                key = str(fact.attributes["obligation_id"]).split(" ", 1)[0]
                names.setdefault(fact.subject.source_id, REGULATION_NAMES.get(key, key))
        return names


def href_obligation(data: PolicyData, obligation_id: str) -> str:
    """Return the address of an obligation's page."""
    key, _, anchor = obligation_id.partition(" ")
    return f"{PREFIX}/{data.corpus}/obligations/{key}/{anchor}"


def obligation_name(data: PolicyData, obligation_id: str) -> str:
    """Name an obligation as a reader cites it: "DORA Article 30(2)"."""
    obligation = data.obligations[obligation_id]
    return f"{REGULATION_NAMES[obligation.regulation]} {obligation.label}"


def href_page(data: PolicyData, page: str = "") -> str:
    """Return the address of one of the corpus's pages: '' for the picture."""
    return f"{PREFIX}/{data.corpus}" + (f"/{page}" if page else "")


def parent_label(anchor: str) -> str:
    """Write a structure anchor as a reader names it: ``article:30`` is "Article 30"."""
    kind, _, value = anchor.partition(":")
    kind = {"subprinciple": "principle"}.get(kind, kind)
    return f"{kind.capitalize()} {value}".strip()


IN_WORDS = {"DORA": "DORA", "AI-ACT": "the AI Act", "SS1-23": "SS1/23"}


def _named(keys: Sequence[str]) -> str:
    """Name regulations as a sentence does: ``DORA, the AI Act and SS1/23``."""
    names = [IN_WORDS[k] for k in IN_WORDS if k in set(keys)]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


# The picture ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class PictureCell:
    """One pairing of an obligation with a document: the state when the assessment cites it."""

    document: str
    state: State | None
    cited: bool

    @property
    def kind(self) -> str:
        """The style key of the state, ``blank`` when the document is not cited."""
        return STATE_KIND[self.state] if self.cited else "blank"


@dataclass(frozen=True)
class PictureRow:
    """One applicable obligation of the picture."""

    obligation_id: str
    label: str
    href: str
    state: State | None
    cells: tuple[PictureCell, ...]


@dataclass(frozen=True)
class PictureGroup:
    """The rows of one article, or one principle, under its chapter."""

    label: str
    rows: tuple[PictureRow, ...]


@dataclass(frozen=True)
class PictureRegulation:
    """One regulation's block of the picture with its population line and tallies."""

    key: str
    name: str
    line: str
    tallies: tuple[tuple[State | None, int], ...]
    groups: tuple[PictureGroup, ...]


@dataclass(frozen=True)
class PictureView:
    """The picture of the obligations that apply against the documents in force."""

    documents: tuple[PolicyDocument, ...]
    regulations: tuple[PictureRegulation, ...]


def population_line(data: PolicyData, regulation: str) -> str:
    """Say how many of a regulation's obligations apply: "101 of 219 DORA obligations apply"."""
    population = data.bundle.obligation_register.population(regulation)
    name = REGULATION_NAMES[regulation]
    noun = "obligation applies" if population.applicable == 1 else "obligations apply"
    return f"{population.applicable} of {population.obligations} {name} {noun}"


def _cited_documents(assessment: Assessment | None) -> dict[str, State]:
    """The documents an assessment quotes, each with the state of the points that quote it."""
    if assessment is None:
        return {}
    cited: dict[str, State] = {}
    for quote in assessment.clause_quotes:
        cited[quote.clause.document] = assessment.state
    return cited


def picture_view(data: PolicyData) -> PictureView:
    """Draw the obligations that apply against the documents in force.

    Args:
        data: The bundle and its documents.

    Returns:
        One block per regulation, the corpus's leading regulation first; each row is an
        obligation that applies, with a cell for each document in force that the assessment
        quotes, and the state of the assessment.
    """
    columns = data.in_force
    blocks = []
    for key in data.regulations:
        groups: dict[str, list[PictureRow]] = {}
        tally: dict[State | None, int] = {}
        for obligation in data.applicable(key):
            assessment = data.assessments.get(obligation.obligation_id)
            state = assessment.state if assessment else None
            tally[state] = tally.get(state, 0) + 1
            cited = _cited_documents(assessment)
            row = PictureRow(
                obligation_id=obligation.obligation_id,
                label=obligation.label,
                href=href_obligation(data, obligation.obligation_id),
                state=state,
                cells=tuple(
                    PictureCell(d.doc_id, cited.get(d.doc_id), d.doc_id in cited) for d in columns
                ),
            )
            chapter = [parent_label(p) for p in obligation.parents]
            label = ", ".join(chapter[:1] + chapter[-1:]) if len(chapter) > 1 else chapter[0]
            groups.setdefault(label, []).append(row)
        order = [*STATES, None]
        blocks.append(
            PictureRegulation(
                key=key,
                name=REGULATION_NAMES[key],
                line=population_line(data, key),
                tallies=tuple((s, tally[s]) for s in order if s in tally),
                groups=tuple(PictureGroup(label, tuple(rows)) for label, rows in groups.items()),
            )
        )
    return PictureView(documents=columns, regulations=tuple(blocks))


def decided_count(data: PolicyData, decisions: Mapping[str, Decision]) -> tuple[int, int]:
    """Count the assessments with a gap that a person has decided on, and all that have one."""
    gaps = [a for a in data.bundle.assessments if a.state in GAP_STATES]
    return sum(a.id in decisions for a in gaps), len(gaps)


def picture_answer(data: PolicyData, decisions: Mapping[str, Decision]) -> Answer:
    """Say what the documents in force state against the provisions, in a sentence and tiles."""
    applicable = len(data.applicable())
    assessed = [a for a in data.bundle.assessments if data.obligations[a.obligation_id].applies]
    counts = {s: sum(a.state == s for a in assessed) for s in STATES}
    gaps = counts["partly covered"] + counts["not covered"] + counts["in conflict"]
    if len(assessed) == applicable:
        sentence = (
            f"Of {_plural(applicable, 'obligation')} that apply to {data.name}, "
            f"{counts['covered']} are covered by the documents in force, "
            f"{counts['partly covered']} partly covered, {counts['not covered']} not covered "
            f"and {counts['in conflict']} in conflict."
        )
    else:
        sentence = (
            f"{len(assessed)} of {applicable} obligations that apply to {data.name} are assessed "
            f"against the documents in force: {counts['covered']} covered, "
            f"{counts['partly covered']} partly covered, {counts['not covered']} not covered "
            f"and {counts['in conflict']} in conflict."
        )
    done, total = decided_count(data, decisions)
    return Answer(
        sentence=sentence,
        tiles=(
            Tile("Obligations that apply", f"{applicable} of {_total(data)}"),
            Tile(
                "With a gap",
                str(gaps),
                "needs_person" if gaps else "normal",
                href=href_page(data, "gap-report"),
            ),
            Tile("Gaps decided", f"{done} of {total}"),
        ),
    )


def _total(data: PolicyData) -> int:
    return sum(p.obligations for p in data.bundle.obligation_register.populations)


# The register --------------------------------------------------------------------------------

REGISTER_COLUMNS = (
    Column("regulation", "Regulation"),
    Column("obligation", "Obligation"),
    Column("applies", "Applies"),
    Column("state", "Found"),
    Column("reason", "Reason"),
)


@dataclass(frozen=True)
class OpenQuestion:
    """An obligation the register leaves to a person, with the register's reason."""

    obligation_id: str
    regulation: str
    label: str
    reason: str
    words: str


def applies_words(obligation: Obligation) -> str:
    """Say whether an obligation applies, in a word or three."""
    return {True: "Applies", False: "Does not apply", None: "Left to a person"}[obligation.applies]


def register_table(
    data: PolicyData,
    *,
    sort: str | None,
    descending: bool,
    href_for: Callable[..., str],
    export_href: str,
) -> TableView:
    """List every obligation of the register, applicable or not, with its reason.

    Args:
        data: The bundle and its documents.
        sort: The column to sort by, or None.
        descending: Whether the sort runs down.
        href_for: Gives the page's address with new sort settings.
        export_href: The address of the CSV of the same rows.

    Returns:
        The table, one row for each of the register's obligations.
    """
    rows = []
    for obligation in data.bundle.obligation_register.obligations:
        assessment = data.assessments.get(obligation.obligation_id)
        open_question = obligation.applies is None
        linked = obligation.applies is True
        rows.append(
            {
                "regulation": Cell(REGULATION_NAMES[obligation.regulation]),
                "obligation": Cell(
                    obligation.label,
                    href=href_obligation(data, obligation.obligation_id) if linked else None,
                    title=f"Open {obligation.label} and what the documents state against it",
                    sort_value=obligation.obligation_id,
                ),
                "applies": Cell(
                    applies_words(obligation), status="needs_person" if open_question else "normal"
                ),
                "state": Cell(STATE_WORDS[assessment.state] if assessment else ""),
                "reason": Cell(obligation.reason),
            }
        )
    return build_table(
        REGISTER_COLUMNS,
        rows,
        sort=sort,
        descending=descending,
        href_for=href_for,
        export_href=export_href,
        caption="Every obligation of the register, in register order",
        empty="The register holds no obligation.",
    )


def open_questions(data: PolicyData) -> tuple[OpenQuestion, ...]:
    """List the obligations the register leaves to a person, each with its reason."""
    return tuple(
        OpenQuestion(
            o.obligation_id,
            REGULATION_NAMES[o.regulation],
            o.label,
            o.reason,
            o.provision_words,
        )
        for o in data.bundle.obligation_register.obligations
        if o.applies is None
    )


def register_answer(data: PolicyData) -> Answer:
    """Say how the register's obligations divide into applying, not applying and open."""
    register = data.bundle.obligation_register
    applies = sum(p.applicable for p in register.populations)
    not_applies = sum(p.not_applicable for p in register.populations)
    undetermined = sum(p.undetermined for p in register.populations)
    total = _total(data)
    units = sum(p.units for p in register.populations)
    named = _named([p.regulation for p in register.populations])
    sentence = (
        f"{total} of {units} units of {named} are obligations: "
        f"{applies} apply to {data.name}, {not_applies} do not and "
        f"{undetermined} are left to a person."
    )
    return Answer(
        sentence=sentence,
        tiles=(
            Tile("Apply", f"{applies} of {total}"),
            Tile("Do not apply", f"{not_applies} of {total}"),
            Tile(
                "Left to a person", str(undetermined), "needs_person" if undetermined else "normal"
            ),
        ),
    )


# One assessment ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ClausePanel:
    """One clause quoted for an obligation, with the document it sits in."""

    document: str
    clause: str
    heading: str
    in_force: bool
    segments: tuple[Segment, ...]
    found: bool


@dataclass(frozen=True)
class PointRow:
    """One top-level point of a provision with its state, its words and the clauses quoted."""

    label: str
    state: State
    gap: str | None
    clauses: tuple[ClausePanel, ...]


@dataclass(frozen=True)
class CandidateRow:
    """A clause code found for the obligation, with whether it was kept and why."""

    document: str
    clause: str
    found_by: str
    matched: str
    kept: bool
    reason: str


@dataclass(frozen=True)
class AssessmentPage:
    """Everything the page of one obligation shows."""

    obligation: Obligation
    assessment: Assessment | None
    provision: tuple[Segment, ...]
    clauses: tuple[ClausePanel, ...]
    points: tuple[PointRow, ...]
    candidates: tuple[CandidateRow, ...]
    checks: tuple[CheckResult, ...]
    reason: str | None
    previous: str | None
    following: str | None


def _panel(data: PolicyData, quote: ClauseQuote) -> ClausePanel:
    document = data.document(quote.clause.document)
    line = document.clause(quote.clause.clause) if document else None
    segments = mark_quote(line.text, quote.quote) if line else None
    return ClausePanel(
        document=document.label if document else quote.clause.document,
        clause=quote.clause.clause,
        heading=line.heading if line else "",
        in_force=document.in_force if document else False,
        segments=segments or (Segment(quote.quote, True),),
        found=segments is not None,
    )


def _point(data: PolicyData, point: PointJudgement) -> PointRow:
    return PointRow(
        label=point.point,
        state=point.state,
        gap=point.gap,
        clauses=tuple(_panel(data, q) for q in point.clause_quotes),
    )


def _candidate(data: PolicyData, candidate: Candidate) -> CandidateRow:
    document = data.document(candidate.clause.document)
    return CandidateRow(
        document=document.label if document else candidate.clause.document,
        clause=candidate.clause.clause,
        found_by=", ".join(FOUND_BY_WORDS[f] for f in candidate.found_by),
        matched=", ".join(candidate.matched),
        kept=candidate.kept,
        reason=candidate.reason,
    )


def assessment_page(data: PolicyData, obligation_id: str) -> AssessmentPage | None:
    """Gather what the page of one applicable obligation shows.

    Args:
        data: The bundle and its documents.
        obligation_id: For example ``DORA art:30/2``.

    Returns:
        The page, or None when the register has no such obligation or it does not apply, since
        only an obligation that applies is assessed.
    """
    obligation = data.obligations.get(obligation_id)
    if obligation is None or obligation.applies is not True:
        return None
    assessment = data.assessments.get(obligation_id)
    listed = [o.obligation_id for o in data.applicable(obligation.regulation)]
    at = listed.index(obligation_id)
    judgement = next(
        (j for j in data.bundle.judgements if j.answer.obligation_id == obligation_id), None
    )
    quote = assessment.provision_quote if assessment else ""
    segments = (mark_quote(obligation.provision_words, quote) if quote else None) or (
        Segment(obligation.provision_words, False),
    )
    return AssessmentPage(
        obligation=obligation,
        assessment=assessment,
        provision=segments,
        clauses=tuple(_panel(data, q) for q in assessment.clause_quotes) if assessment else (),
        points=tuple(_point(data, p) for p in assessment.points) if assessment else (),
        candidates=tuple(
            _candidate(data, c) for c in data.bundle.candidates if c.obligation_id == obligation_id
        ),
        checks=tuple(assessment.checks) if assessment else (),
        reason=judgement.answer.reason if judgement else None,
        previous=href_obligation(data, listed[at - 1]) if at else None,
        following=href_obligation(data, listed[at + 1]) if at + 1 < len(listed) else None,
    )


def assessment_answer(page: AssessmentPage, decision: Decision | None) -> Answer:
    """Say what the documents in force state against one provision, in one sentence."""
    label = f"{REGULATION_NAMES[page.obligation.regulation]} {page.obligation.label}"
    if page.assessment is None:
        return Answer(sentence=f"{label} has not been assessed against the documents in force.")
    state = STATE_WORDS[page.assessment.state].lower()
    sentence = f"{label} is {state} by the documents in force."
    return Answer(
        sentence=sentence,
        tiles=(
            Tile("Found", STATE_WORDS[page.assessment.state]),
            Tile("Clauses quoted", str(len(page.assessment.clause_quotes))),
            Tile(
                "Your decision",
                "Decided" if decision else "Waiting",
                "normal" if decision else "needs_person",
            ),
        ),
    )


def _end(text: str) -> str:
    words = text.strip()
    return words if words.endswith((".", "?", "!")) else f"{words}."


# The clauses ---------------------------------------------------------------------------------

CLAUSE_COLUMNS = (
    Column("document", "Document"),
    Column("clause", "Clause"),
    Column("heading", "Section"),
    Column("mapped", "Obligations it answers"),
)


def clauses_table(
    data: PolicyData,
    *,
    sort: str | None,
    descending: bool,
    href_for: Callable[..., str],
    export_href: str,
) -> TableView:
    """List every clause of the documents in force, mapped to obligations or with its reason."""
    rows = []
    for mapping in data.bundle.clause_map:
        document = data.document(mapping.clause.document)
        line = document.clause(mapping.clause.clause) if document else None
        if mapping.obligations:
            mapped = Cell(
                "; ".join(mapping.obligations),
                href=href_obligation(data, mapping.obligations[0])
                if data.obligations.get(mapping.obligations[0]) is not None
                and data.obligations[mapping.obligations[0]].applies
                else None,
            )
        else:
            mapped = Cell(mapping.unmapped_reason or "", status="needs_person")
        rows.append(
            {
                "document": Cell(document.label if document else mapping.clause.document),
                "clause": Cell(mapping.clause.clause, sort_value=mapping.clause.clause),
                "heading": Cell(line.heading if line else ""),
                "mapped": mapped,
            }
        )
    return build_table(
        CLAUSE_COLUMNS,
        rows,
        sort=sort,
        descending=descending,
        href_for=href_for,
        export_href=export_href,
        caption="Every clause of the documents in force",
        empty="No clause is in force.",
    )


def clauses_answer(data: PolicyData) -> Answer:
    """Say how many clauses of the documents in force answer an obligation."""
    mapped = sum(bool(m.obligations) for m in data.bundle.clause_map)
    total = len(data.bundle.clause_map)
    return Answer(
        sentence=(
            f"{mapped} of {_plural(total, 'clause')} in the {len(data.in_force)} documents "
            f"in force answer an obligation that applies to {data.name}."
        ),
        tiles=(
            Tile("Clauses in force", str(total)),
            Tile("Answer an obligation", f"{mapped} of {total}"),
            Tile("With no obligation", str(total - mapped)),
        ),
    )


# The graph -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Edge:
    """One edge of the document graph with the words at both ends."""

    relation: str
    words: str
    from_name: str
    from_place: str
    from_quote: str
    to_name: str
    to_place: str
    to_quote: str


def place_words(anchor: str) -> str:
    """Write a place of a document or a regulation as a reader names it."""
    kind, _, value = anchor.partition(":")
    if kind == "clause":
        return f"Clause {value}"
    if kind == "control":
        return f"Document control, {value.replace('_', ' ')} line"
    if kind == "art":
        article, _, rest = value.partition("/")
        return f"Article {article}" + (f"({rest})" if rest else "")
    return anchor


def graph_edges(data: PolicyData) -> tuple[Edge, ...]:
    """List the graph's facts, each with both ends and the words at them."""
    names = data.source_names()
    edges = []
    for fact in data.bundle.facts:
        if fact.kind not in RELATIONS:
            continue
        attributes = fact.attributes
        relation = str(fact.kind)
        edges.append(
            Edge(
                relation=relation,
                words=RELATION_WORDS[relation],
                from_name=names.get(fact.subject.source_id, "A document"),
                from_place=place_words(fact.subject.anchor),
                from_quote=fact.quote,
                to_name=names.get(str(attributes.get("object_source_id", "")), "A document"),
                to_place=place_words(str(attributes.get("object_anchor", ""))),
                to_quote=str(attributes.get("object_quote", "")),
            )
        )
    return tuple(edges)


def graph_answer(edges: Sequence[Edge], data: PolicyData) -> Answer:
    """Say how many relations the documents' graph holds."""
    kinds = sorted({e.relation for e in edges})
    return Answer(
        sentence=(
            f"The documents of {data.name} and the regulations hold "
            f"{_plural(len(edges), 'relation')} "
            f"that code found with a quote at each end."
            if edges
            else f"No relation was found between the documents of {data.name}."
        ),
        tiles=(Tile("Relations", str(len(edges))), Tile("Kinds", str(len(kinds)))),
    )


# The gap report ------------------------------------------------------------------------------


@dataclass(frozen=True)
class GapStatement:
    """One statement of the gap report, the assessment behind it and its decision."""

    heading: str
    text: str
    obligation_id: str
    label: str
    href: str
    assessment_id: str
    state: State
    decision: Decision | None


def _placed(data: PolicyData) -> list[tuple[Statement, Assessment | None]]:
    """Pair each statement of the gap report with the assessment whose facts it cites, if any."""
    by_evidence: dict[str, Assessment] = {}
    for assessment in data.bundle.assessments:
        for fact_id in assessment.evidence:
            by_evidence.setdefault(fact_id, assessment)
    return [
        (statement, next((by_evidence[c] for c in statement.cites if c in by_evidence), None))
        for statement in data.bundle.gap_report.statements
    ]


def gap_statements(data: PolicyData, decisions: Mapping[str, Decision]) -> tuple[GapStatement, ...]:
    """List the gap report's statements with the assessment each rests on and its decision.

    A statement cites the facts of one assessment; the assessment is found by those facts. A
    statement that cites no assessment's fact is not listed here; ``unplaced_statements`` has it.
    """
    return tuple(
        GapStatement(
            heading=REGULATION_NAMES.get(statement.heading or "", statement.heading or ""),
            text=statement.text,
            obligation_id=assessment.obligation_id,
            label=obligation_name(data, assessment.obligation_id),
            href=href_obligation(data, assessment.obligation_id),
            assessment_id=assessment.id,
            state=assessment.state,
            decision=decisions.get(assessment.id),
        )
        for statement, assessment in _placed(data)
        if assessment is not None
    )


def unplaced_statements(data: PolicyData) -> tuple[Statement, ...]:
    """List the gap report's statements that cite no fact of any assessment.

    Nobody can decide such a statement, so the report is not signed over it.
    """
    return tuple(statement for statement, assessment in _placed(data) if assessment is None)


def _without_decision_by(statement: GapStatement, person: Person | None) -> bool:
    """Say whether a gap lacks a decision from the person; any decision counts for nobody."""
    return statement.decision is None or (
        person is not None and statement.decision.reviewer != person
    )


def cannot_sign_because(
    data: PolicyData, decisions: Mapping[str, Decision], *, person: Person | None = None
) -> str | None:
    """Say why the gap report cannot be signed yet, or None when it can.

    Args:
        data: The bundle and its documents.
        decisions: The decisions held, by assessment id.
        person: The person who would sign; only their own decisions count, as in the brief. When
            absent, a decision by anyone counts.

    Returns:
        A sentence naming a statement that rests on no assessment, decisions made by someone
        else, how many gaps have no decision from the person, or that a gap was rejected; None
        when every gap is decided by the person and none rejected.
    """
    unplaced = unplaced_statements(data)
    if unplaced:
        named = "; ".join(f"{s.heading or 'No heading'}: {s.text}" for s in unplaced)
        return (
            f"The gap report cannot be signed yet: {_plural(len(unplaced), 'statement')} "
            f"{'rests' if len(unplaced) == 1 else 'rest'} on no assessment, so no one can decide "
            f"{'it' if len(unplaced) == 1 else 'them'} ({named})."
        )
    statements = gap_statements(data, decisions)
    if person is not None:
        others = sorted(
            {
                f"{s.decision.reviewer.name}, {s.decision.reviewer.role}"
                for s in statements
                if s.decision is not None and s.decision.reviewer != person
            }
        )
        if others:
            return (
                f"Decisions on this gap report were made by {', '.join(others)}. Sign in as that "
                "person to sign it, or record your own decisions again."
            )
    waiting = [s for s in statements if _without_decision_by(s, person)]
    rejected = [s for s in statements if s.decision is not None and s.decision.outcome == "reject"]
    if waiting:
        return (
            f"The gap report cannot be signed yet: {_plural(len(waiting), 'gap')} "
            f"{'has' if len(waiting) == 1 else 'have'} no decision from you."
        )
    if rejected:
        return (
            f"You rejected {_plural(len(rejected), 'gap')}, so the gap report can be returned "
            "but not signed."
        )
    return None


def next_open_gap(
    data: PolicyData,
    decisions: Mapping[str, Decision],
    *,
    person: Person | None,
    after: str | None = None,
) -> str | None:
    """Give the address of the next gap that has no decision from the person.

    The gaps are those the gap report's statements rest on, in the register's order. The search
    starts after the obligation the person is on and wraps round, so a person can work through
    the gaps; the obligation they are on is never given back.

    Args:
        data: The bundle and its documents.
        decisions: The decisions held, by assessment id.
        person: Whose decisions count; anyone's when None.
        after: The obligation the person is on, or None to start from the first.

    Returns:
        The address of the assessment page, or None when every gap has the person's decision.
    """
    open_gaps = {
        s.obligation_id for s in gap_statements(data, decisions) if _without_decision_by(s, person)
    }
    order = [o.obligation_id for o in data.applicable()]
    start = order.index(after) + 1 if after in order else 0
    for obligation_id in [*order[start:], *order[:start]]:
        if obligation_id in open_gaps and obligation_id != after:
            return href_obligation(data, obligation_id)
    return None


def gap_report_answer(
    data: PolicyData, decisions: Mapping[str, Decision], blocker: str | None
) -> Answer:
    """Say where the gap report stands for the reviewer."""
    statements = gap_statements(data, decisions)
    done = sum(s.decision is not None for s in statements)
    sentence = f"The gap report for {data.name} holds {_plural(len(statements), 'statement')}. " + (
        blocker or "Every gap is decided, so it is ready for you to sign."
    )
    return Answer(
        sentence=sentence,
        tiles=(
            Tile("Statements", str(len(statements))),
            Tile("Decided", f"{done} of {len(statements)}"),
            Tile("Sources", str(len(data.bundle.gap_report.sources))),
        ),
    )


# What the run left out ------------------------------------------------------------------------


@dataclass(frozen=True)
class NotIncludedLine:
    """A regulation the run left out, in the words the picture page gives, and its commands."""

    name: str
    sentence: str
    commands: tuple[str, ...]


def not_included_lines(data: PolicyData) -> tuple[NotIncludedLine, ...]:
    """Say, for each regulation the bundle's index names as left out, why and how to include it.

    The reason and the commands are the bundle's own words; nothing about the regulation is
    counted or drawn.

    Args:
        data: The bundle and its documents.

    Returns:
        One line for each regulation left out, in the index's order.
    """
    lines = []
    for left in data.bundle.index.not_included:
        name = REGULATION_NAMES[left.regulation]
        reason = left.reason.strip().rstrip(".")
        lines.append(
            NotIncludedLine(
                name=name,
                sentence=f"{name} is not included here: {reason}. To include it:",
                commands=tuple(left.commands),
            )
        )
    return tuple(lines)


# The figures of the run -----------------------------------------------------------------------


@dataclass(frozen=True)
class Figure:
    """One figure of the run: how many of a stated population, and what is counted."""

    key: str
    label: str
    found: int
    of: int
    what: str

    @property
    def result(self) -> str:
        """The figure as "N of M"."""
        return f"{self.found} of {self.of}"


def measure_figures(data: PolicyData) -> tuple[Figure, ...]:
    """Count how the run's findings compare with the seeded cases, from the bundle's matches.

    Each figure is a count over a stated population, as the measures define them: a seed is
    matched to the assessments at its place, its found state is compared with the state a person
    gave it, and its cited clauses with the clauses that person gave.

    Args:
        data: The bundle and its documents.

    Returns:
        The four figures: seeded gaps found, covered seeds called a gap, citations wrong, and
        seeds found in the same state.
    """
    matches = data.bundle.seed_matches
    gaps = [m for m in matches if m.seeded_state in GAP_STATES]
    covered = [m for m in matches if m.seeded_state == "covered"]
    cited = [m for m in matches if m.seeded_clauses and m.found_state != "not covered"]
    wrong = [
        m for m in cited if not set(map(_ref, m.cited_clauses)) & set(map(_ref, m.seeded_clauses))
    ]
    return (
        Figure(
            "gaps_found",
            "Seeded gaps found",
            sum(m.found_state != "covered" for m in gaps),
            len(gaps),
            "Seeded cases whose state is partly covered, not covered or in conflict, that the run "
            "also found as a gap",
        ),
        Figure(
            "false_gaps",
            "Covered seeds called a gap",
            sum(m.found_state != "covered" for m in covered),
            len(covered),
            "Seeded cases whose state is covered, that the run found as a gap",
        ),
        Figure(
            "wrong_citations",
            "Citations that name no seeded clause",
            len(wrong),
            len(cited),
            "Findings on seeded cases with seeded clauses, where none of the clauses cited is one "
            "of those",
        ),
        Figure(
            "same_state",
            "Seeds found in the same state",
            sum(m.found_state == m.seeded_state for m in matches),
            len(matches),
            "Seeded cases the run found in the state a person gave them",
        ),
    )


PROPOSAL = "Every finding is a proposal that a person decides."


def proposal_sentence(data: PolicyData) -> str:
    """Say that findings are proposals, and where among the gaps the engine asks for a person most.

    The state named is the one with the most gaps in the bundle, or the states that tie for it;
    nothing is named when the bundle holds no gap.

    Args:
        data: The bundle and its documents.

    Returns:
        The sentence for the measures page.
    """
    counts = {s: sum(a.state == s for a in data.bundle.assessments) for s in GAP_STATES}
    most = max(counts.values())
    if most == 0:
        return PROPOSAL
    largest = [f'"{STATE_WORDS[s]}"' for s in GAP_STATES if counts[s] == most]
    named = largest[0] if len(largest) == 1 else f"{', '.join(largest[:-1])} and {largest[-1]}"
    verb = "is" if len(largest) == 1 else "are"
    return f"{PROPOSAL} {named} {verb} where the engine asks for a person most."


def _ref(ref: object) -> tuple[str, str]:
    return (ref.document, ref.clause)  # type: ignore[attr-defined]


def measures_answer(figures: Sequence[Figure], data: PolicyData) -> Answer:
    """Say in one sentence how the run's findings compare with the seeded cases."""
    by = {f.key: f for f in figures}
    if by["same_state"].of == 0:
        return Answer(sentence=f"The documents of {data.name} have no seeded case to compare with.")
    gaps, same = by["gaps_found"], by["same_state"]
    return Answer(
        sentence=(
            f"The run found {gaps.found} of {gaps.of} seeded gaps, and {same.found} of {same.of} "
            "seeded cases in the state a person gave them."
        ),
        tiles=(Tile(gaps.label, gaps.result), Tile(same.label, same.result)),
    )
