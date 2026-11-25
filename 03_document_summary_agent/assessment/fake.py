"""A fake engine: a small, valid bundle built from the real Harbour Mutual Bank set and its seeds.

The pages and the measures build on it before the engine exists. Its states and quotes come from
eight seeds of ``policy_seeds.tsv``; every other point of those provisions is given a state so
the derived states close. It is labelled ``run: fake`` and narrows its scope to the obligations
it assesses, which only a fake run may do. ``plant_invalid_bundle`` breaks one rule at a time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from assessment.bundle import FACT_CONTEXT
from assessment.profile import load_profile
from assessment.provisions import Seed, derive_state, load_seeds, match_seed, resolve_provision
from assessment.records import (
    Assessment,
    Bundle,
    BundleIndex,
    Candidate,
    CandidateText,
    ClauseMapping,
    ClauseQuote,
    ClauseRef,
    Judgement,
    JudgementAnswer,
    JudgementRequest,
    Obligation,
    PointJudgement,
    Register,
    SeedMatch,
    State,
)
from assessment.register import build_register
from assessment.texts import TextIndex
from fsi_common.ids import digest_json
from fsi_common.records import (
    Brief,
    CheckResult,
    ClaimStatus,
    Extractor,
    Fact,
    Provenance,
    SourceRef,
    Statement,
)

FAKE_SEEDS = (
    "DORA-01",
    "DORA-09",
    "DORA-15",
    "DORA-22",
    "DORA-23",
    "AIA-08",
    "SS123-01",
    "SS123-15",
)
"""The seeds the fake assesses: every state, a point-level seed, a node-level seed, a gap."""

EXTRACTOR = Extractor(name="fake-engine", version="0.1.0")
_PASS = "quote-verbatim.v1"
_NO_CLAUSE_GAP = "No clause of the documents in force was found for this provision on two looks."
_PART_GAP = "The documents in force state part of what the provision requires."
_SUPERSEDED_QUOTE = "The Management Body defines, approves, oversees and is responsible"
"""Words of clause 4.1 of the superseded ICT Risk Management Policy, version 2.1."""


@dataclass
class _Plan:
    obligation: Obligation
    unit_seed: Seed | None = None
    point_seeds: dict[str, Seed] = field(default_factory=dict)
    quotes: list[ClauseQuote] = field(default_factory=list)
    state: State = "not covered"


def _lead(text: str, words: int = 14) -> str:
    return " ".join(text.split()[:words])


def _check(detail: str) -> list[CheckResult]:
    return [CheckResult(check=_PASS, outcome="pass", detail=detail)]


def _digest_of(texts: TextIndex, source_id: str) -> str:
    for read in texts.regulations.values():
        if read.source.id == source_id:
            return read.source.digest
    return next(d.source.digest for d in texts.corpus.documents if d.source.id == source_id)


def _fact(
    texts: TextIndex, *, kind: str, source_id: str, anchor: str, quote: str, **attrs: str
) -> Fact:
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
            as_of=_digest_of(texts, source_id),
        ),
        checks=_check(f"the quote lies word for word at {anchor}"),
    )


def _seed_quotes(seed: Seed) -> list[ClauseQuote]:
    return [
        ClauseQuote(clause=ClauseRef(document=d, clause=c), quote=q)
        for (d, c), q in zip(seed.clauses, seed.clause_quotes, strict=True)
    ]


def _unique(quotes: list[ClauseQuote]) -> list[ClauseQuote]:
    return list({(q.clause.document, q.clause.clause, q.quote): q for q in quotes}.values())


def _points(plan: _Plan) -> list[PointJudgement]:
    if not plan.obligation.points:
        return []
    seeded = [q for s in plan.point_seeds.values() for q in _seed_quotes(s)]
    base: State = "covered" if plan.point_seeds else plan.state
    out = []
    for point in plan.obligation.points:
        seed = plan.point_seeds.get(point)
        state = seed.state if seed else base
        quotes = _seed_quotes(seed) if seed else (plan.quotes or seeded)
        gap = None
        if state != "covered":
            gap = (
                f"Point ({point}) is not stated in the documents in force as the provision has it."
            )
        out.append(PointJudgement(point=point, state=state, clause_quotes=quotes, gap=gap))
    return out


def _request(texts: TextIndex, plan: _Plan, quotes: list[ClauseQuote]) -> JudgementRequest:
    candidates = []
    for q in quotes:
        entry = texts.corpus.document(q.clause.document)
        clause = next(c for c in texts.clauses[q.clause.document] if c.number == q.clause.clause)
        candidates.append(
            CandidateText(
                clause=q.clause,
                document_title=entry.entry.title if entry else q.clause.document,
                version=q.clause.document.rsplit("-", 1)[-1],
                in_force=texts.in_force(q.clause.document),
                heading=clause.heading,
                text=clause.text,
            )
        )
    o = plan.obligation
    return JudgementRequest(
        obligation_id=o.obligation_id,
        label=o.label,
        provision_words=o.provision_words,
        points=o.points,
        applies_to=o.applies_to,
        candidates=candidates,
        defined_terms={},
        prompt_version="assess.v1",
    )


def _assess(
    texts: TextIndex, plan: _Plan
) -> tuple[Assessment, list[Fact], list[Candidate], Judgement | None]:
    o = plan.obligation
    seed = plan.unit_seed
    quote = (
        seed.provision_quote
        if seed and texts.provision_has(o.regulation, o.anchor, seed.provision_quote)
        else _lead(o.provision_words)
    )
    points = _points(plan)
    quotes = _unique(plan.quotes + [q for p in points for q in p.clause_quotes])
    source_id = texts.regulation_source(o.regulation).id
    facts = [
        _fact(
            texts,
            kind="provision",
            source_id=source_id,
            anchor=o.anchor,
            quote=quote,
            obligation_id=o.obligation_id,
        )
    ]
    facts += [
        _fact(
            texts,
            kind="clause",
            source_id=texts.source(q.clause.document).id,
            anchor=q.clause.anchor,
            quote=q.quote,
            obligation_id=o.obligation_id,
        )
        for q in quotes
    ]
    candidates = [
        Candidate(
            obligation_id=o.obligation_id,
            clause=q.clause,
            found_by=["term"],
            matched=[_lead(q.quote, 3)],
            kept=True,
            reason="shares the provision's terms and sits in a document in force",
        )
        for q in quotes
    ]
    state = derive_state(p.state for p in points) if points else plan.state
    by_model = bool(quotes)
    gap = None if state == "covered" else (_PART_GAP if by_model else _NO_CLAUSE_GAP)
    assessment = Assessment.build(
        obligation_id=o.obligation_id,
        regulation=o.regulation,
        state=state,
        provision_quote=quote,
        clause_quotes=quotes,
        gap=gap,
        suggested_wording=None,
        points=points,
        second_look=not by_model,
        assessed_by="model" if by_model else "code",
        evidence=[f.id for f in facts],
        checks=_check("both quotes lie word for word in their texts"),
    )
    if not by_model:
        return assessment, facts, candidates, None
    request = _request(texts, plan, quotes)
    answer = JudgementAnswer(
        obligation_id=o.obligation_id,
        state=state,
        provision_quote=quote,
        clause_quotes=quotes,
        gap=gap,
        suggested_wording=None,
        points=points,
        reason="Fake answer, built from the seed register for the pages and the measures.",
    )
    judgement = Judgement(
        role="assess",
        model="fake-engine",
        request_digest=digest_json(request.model_dump(mode="json")),
        request=request,
        answer=answer,
    )
    return assessment, facts, candidates, judgement


def _clause_with(texts: TextIndex, doc: str, words: str, section: str = "") -> str:
    return next(
        f"clause:{c.number}"
        for c in texts.clauses[doc]
        if words in c.text and c.number.startswith(section)
    )


def _graph(texts: TextIndex) -> list[Fact]:
    gov, ict, old = "HMB-FRM-GOV-000-v2.0", "HMB-POL-ICT-001-v3.0", "HMB-POL-ICT-001-v2.1"
    ai, mrm = "HMB-STD-AI-014-v1.0", "HMB-POL-MRM-004-v2.0"
    dora = texts.regulation_source("DORA").id
    src = {d: texts.source(d).id for d in (gov, ict, old, ai, mrm)}
    edges = [
        ("supersedes", src[ict], "control:supersedes", src[old], "control:superseded_by", None),
        ("implements", src[ict], "clause:1.2", dora, "art:6/1", None),
        ("refers_to", src[ai], "clause:2.5", src[mrm], "control:reference", None),
        (
            "defines",
            src[gov],
            _clause_with(texts, gov, '"Management Body" means'),
            src[ict],
            _clause_with(texts, ict, "Management Body"),
            "Management Body",
        ),
        (
            "delegates",
            src[gov],
            _clause_with(texts, gov, "Executive Risk Committee", "5."),
            src[ai],
            "control:approved_by",
            None,
        ),
    ]
    facts = []
    for relation, source_id, anchor, object_source, object_anchor, object_quote in edges:
        facts.append(
            _fact(
                texts,
                kind=relation,
                source_id=source_id,
                anchor=anchor,
                quote=_lead(texts.text_at(source_id, anchor) or "", 10),
                object_source_id=object_source,
                object_anchor=object_anchor,
                object_quote=object_quote
                or _lead(texts.text_at(object_source, object_anchor) or "", 10),
            )
        )
    return facts


def found_state(seed: Seed, register: Register, by_id: dict[str, Assessment]) -> State:
    """Return the state the assessments give at a seed's place.

    Args:
        seed: The seed.
        register: The register.
        by_id: The assessments, by obligation id.

    Returns:
        A point's state where the seed names a point the unit has; the unit's state where it is
        one obligation; else the state derived over every obligation at the place.

    Raises:
        KeyError: If an obligation at the seed's place was not assessed.
    """
    ref = resolve_provision(seed.regulation, seed.provision)
    targets = [o.obligation_id for o in match_seed(seed, register)]
    if len(targets) == 1:
        assessment = by_id[targets[0]]
        point = next((p for p in assessment.points if ref.points[:1] == (p.point,)), None)
        return point.state if point else assessment.state
    return derive_state(by_id[t].state for t in targets)


def _seed_match(seed: Seed, register: Register, by_id: dict[str, Assessment]) -> SeedMatch:
    ref = resolve_provision(seed.regulation, seed.provision)
    targets = [o.obligation_id for o in match_seed(seed, register)]
    return SeedMatch(
        seed_id=seed.seed_id,
        regulation=seed.regulation,  # type: ignore[arg-type]
        target=ref.anchor,
        points=list(ref.points),
        obligation_ids=targets,
        found_state=found_state(seed, register, by_id),
        seeded_state=seed.state,
        cited_clauses=[q.clause for t in targets for q in by_id[t].clause_quotes],
        seeded_clauses=[ClauseRef(document=d, clause=c) for d, c in seed.clauses],
    )


def _plans(register: Register, seeds: dict[str, Seed]) -> dict[str, _Plan]:
    plans: dict[str, _Plan] = {}
    for seed in seeds.values():
        ref = resolve_provision(seed.regulation, seed.provision)
        targets = match_seed(seed, register)
        for index, obligation in enumerate(targets):
            plan = plans.setdefault(obligation.obligation_id, _Plan(obligation=obligation))
            if len(targets) > 1:
                plan.state = "covered" if index == 0 else "not covered"
                plan.quotes = _seed_quotes(seed) if index == 0 else []
            elif ref.points and ref.points[0] in obligation.points:
                plan.point_seeds[ref.points[0]] = seed
            else:
                plan.unit_seed, plan.state, plan.quotes = seed, seed.state, _seed_quotes(seed)
    return plans


def _clause_map(texts: TextIndex, assessments: list[Assessment]) -> list[ClauseMapping]:
    quoted: dict[tuple[str, str], list[str]] = {}
    for a in assessments:
        for q in a.clause_quotes:
            ids = quoted.setdefault((q.clause.document, q.clause.clause), [])
            if a.obligation_id not in ids:
                ids.append(a.obligation_id)
    return [
        ClauseMapping(
            clause=ClauseRef(document=doc, clause=c.number),
            obligations=quoted.get((doc, c.number), []),
            unmapped_reason=None if (doc, c.number) in quoted else "outside the fake run's scope",
        )
        for doc, clauses in texts.clauses.items()
        if texts.in_force(doc)
        for c in clauses
    ]


def build_fake_bundle(texts: TextIndex) -> Bundle:
    """Build the fake bundle on the real texts.

    Args:
        texts: The regulations and the Harbour Mutual Bank set, read whole.

    Returns:
        A bundle that passes ``validate_bundle``.
    """
    register = build_register(texts, load_profile("harbour-mutual-bank"))
    seeds = {s.seed_id: s for s in load_seeds() if s.seed_id in FAKE_SEEDS}
    assessments: list[Assessment] = []
    facts: list[Fact] = []
    candidates: list[Candidate] = []
    judgements: list[Judgement] = []
    for plan in _plans(register, seeds).values():
        assessment, made, found, judgement = _assess(texts, plan)
        assessments.append(assessment)
        facts.extend(made)
        candidates.extend(found)
        if judgement is not None:
            judgements.append(judgement)
    facts = list({f.id: f for f in facts + _graph(texts)}.values())
    by_id = {a.obligation_id: a for a in assessments}
    sources = [r.source.id for r in texts.regulations.values()]
    sources += [d.source.id for d in texts.corpus.documents]
    statements = []
    for a in assessments:
        obligation = register.obligation(a.obligation_id)
        if a.state != "covered" and obligation is not None:
            text = f"{obligation.label}: {a.gap}"
            statements.append(Statement.build(heading=a.regulation, text=text, cites=a.evidence))
    report = Brief.build(
        request=(
            "Gap report of the Harbour Mutual Bank policy set against DORA, the AI Act and SS1/23"
        ),
        sources=sources,
        statements=statements,
        open_question_ids=[],
        model="fake-engine",
        prompt_version="assess.v1",
    )
    index = BundleIndex(
        corpus="harbour-mutual-bank",
        run="fake",
        scope=sorted(by_id),
        source_ids=sources,
        counts={
            "assessments": len(assessments),
            "judgements": len(judgements),
            "facts": len(facts),
        },
    )
    return Bundle(
        index=index,
        obligation_register=register,
        candidates=candidates,
        judgements=judgements,
        assessments=assessments,
        facts=facts,
        clause_map=_clause_map(texts, assessments),
        seed_matches=[_seed_match(seeds[s], register, by_id) for s in FAKE_SEEDS],
        gap_report=report,
    )


def _first(bundle: Bundle, test: Callable[[Assessment], bool]) -> int:
    return next(i for i, a in enumerate(bundle.assessments) if test(a))


def _replace(bundle: Bundle, index: int, **update: object) -> Bundle:
    items = list(bundle.assessments)
    items[index] = items[index].model_copy(update=update)
    return bundle.model_copy(update={"assessments": items})


def _plant_clause_quote(bundle: Bundle) -> Bundle:
    i = _first(bundle, lambda a: bool(a.clause_quotes))
    quotes = [
        q.model_copy(update={"quote": q.quote + " and every other rule"})
        for q in bundle.assessments[i].clause_quotes
    ]
    return _replace(bundle, i, clause_quotes=quotes)


def _plant_superseded(bundle: Bundle) -> Bundle:
    i = _first(bundle, lambda a: a.state == "covered" and not a.points)
    quote = ClauseQuote(
        clause=ClauseRef(document="HMB-POL-ICT-001-v2.1", clause="4.1"), quote=_SUPERSEDED_QUOTE
    )
    return _replace(bundle, i, clause_quotes=[quote])


def _plant_graph(bundle: Bundle) -> Bundle:
    facts = list(bundle.facts)
    i = next(i for i, f in enumerate(facts) if f.kind == "supersedes")
    attributes = {**facts[i].attributes, "object_quote": "Superseded by nothing at all"}
    facts[i] = facts[i].model_copy(update={"attributes": attributes})
    return bundle.model_copy(update={"facts": facts})


def _plant_unaccounted(bundle: Bundle) -> Bundle:
    register = bundle.obligation_register
    shorter = register.model_copy(update={"dispositions": register.dispositions[1:]})
    return bundle.model_copy(update={"obligation_register": shorter})


def _plant_inapplicable(bundle: Bundle) -> Bundle:
    other = next(o for o in bundle.obligation_register.obligations if o.applies is False)
    return _replace(bundle, 0, obligation_id=other.obligation_id)


def _plant_graph_subject(bundle: Bundle) -> Bundle:
    facts = list(bundle.facts)
    i = next(i for i, f in enumerate(facts) if f.kind == "refers_to")
    facts[i] = facts[i].model_copy(update={"quote": "Where nothing at all is said"})
    return bundle.model_copy(update={"facts": facts})


def _plant_seed_match(bundle: Bundle) -> Bundle:
    matches = list(bundle.seed_matches)
    flipped: State = "in conflict" if matches[0].found_state != "in conflict" else "covered"
    matches[0] = matches[0].model_copy(update={"found_state": flipped})
    return bundle.model_copy(update={"seed_matches": matches})


_PLANTS: dict[str, Callable[[Bundle], Bundle]] = {
    "clause-quote-not-verbatim": _plant_clause_quote,
    "provision-quote-not-verbatim": lambda b: _replace(
        b, 0, provision_quote=b.assessments[0].provision_quote + " in every case"
    ),
    "applicable-obligation-not-assessed": lambda b: b.model_copy(
        update={"assessments": b.assessments[1:]}
    ),
    "clause-neither-mapped-nor-listed": lambda b: b.model_copy(
        update={"clause_map": b.clause_map[1:]}
    ),
    "not-covered-without-second-look": lambda b: _replace(
        b, _first(b, lambda a: a.assessed_by == "code"), second_look=False
    ),
    "superseded-clause-covers": _plant_superseded,
    "graph-fact-object-quote": _plant_graph,
    "derived-state-mismatch": lambda b: _replace(
        b, _first(b, lambda a: bool(a.points) and a.state == "partly covered"), state="not covered"
    ),
    "compliance-words": lambda b: _replace(
        b, _first(b, lambda a: a.state != "covered"), gap="The Bank does not comply with it."
    ),
    "gap-missing": lambda b: _replace(
        b, _first(b, lambda a: a.state == "partly covered"), gap=None
    ),
    "state-without-clause": lambda b: _replace(
        b, _first(b, lambda a: a.state == "covered" and not a.points), clause_quotes=[]
    ),
    "register-unit-unaccounted": _plant_unaccounted,
    "inapplicable-obligation-assessed": _plant_inapplicable,
    "graph-fact-subject-quote": _plant_graph_subject,
    "points-incomplete": lambda b: _replace(
        b,
        _first(b, lambda a: bool(a.points)),
        points=b.assessments[_first(b, lambda a: bool(a.points))].points[:-1],
    ),
    "evidence-missing": lambda b: _replace(b, 0, evidence=["fact:0000000000000000"]),
    "judgement-missing": lambda b: b.model_copy(update={"judgements": []}),
    "seed-match-wrong": _plant_seed_match,
    "partial-scope": lambda b: b.model_copy(
        update={"index": b.index.model_copy(update={"run": "replay"})}
    ),
}


def plant_invalid_bundle(bundle: Bundle, fault: str) -> Bundle:
    """Break one rule of a valid bundle, so the check that guards it can be seen to fail.

    Args:
        bundle: A valid bundle.
        fault: The name of the check to break, one of ``assessment.validate.CHECKS``.

    Returns:
        The bundle with that one fault planted.

    Raises:
        KeyError: If there is no planted fault by that name.
    """
    if fault not in _PLANTS:
        raise KeyError(f"There is no planted fault {fault!r}; the faults are {', '.join(_PLANTS)}.")
    return _PLANTS[fault](bundle)
