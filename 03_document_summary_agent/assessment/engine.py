"""The engine: register, graph, candidates, one judgement per obligation, a checked bundle.

``prepare`` does everything that needs no model: the register, the graph, the candidates of both
looks, and so the number of calls, which ``plan_of`` states before any call is made.
``assess_async`` makes the calls, at most ``concurrency`` at a time, each request depending on its
obligation and its candidates alone, so a replay matches whatever order the calls finish in.
Every answer is checked by code and asked again, with the faults named, up to ``MAX_TRIES``
times; an obligation whose answer still fails is reported by name, and no part of its answer is
used. Nothing here makes a call except through the judge it is given.
"""

from __future__ import annotations

import asyncio
import math
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from assessment.candidates import find_candidates, without_candidates
from assessment.graph import build_graph, lead, make_fact
from assessment.interfaces import PROMPT_VERSION
from assessment.judge import (
    AsyncJudge,
    JudgeReplyError,
    check_answer,
    definitions,
    digest_of,
    load_instructions,
    make_request,
    request_digest,
)
from assessment.profile import load_profile
from assessment.provisions import Seed, derive_state, load_seeds, match_seed, resolve_provision
from assessment.records import (
    Assessment,
    Bundle,
    BundleIndex,
    Candidate,
    ClauseMapping,
    ClauseQuote,
    ClauseRef,
    FirmProfile,
    Judgement,
    JudgementAnswer,
    JudgementRequest,
    NotIncluded,
    Obligation,
    PointJudgement,
    Register,
    SeedMatch,
    State,
)
from assessment.register import build_register
from assessment.texts import TextIndex, load_texts
from assessment.validate import require_valid
from context.errors import ContextError
from fsi_common.model.errors import ModelError
from fsi_common.records import Brief, CheckResult, Fact, Statement
from utils.models import MAX_CONCURRENCY

DEFAULT_CONCURRENCY = MAX_CONCURRENCY
"""How many judgement calls run at once: the one limit ``utils.models`` allows."""

MAX_TRIES = 3
"""How many times an obligation's answer is asked for before it is refused."""

QUOTE_CHECK = "quote-verbatim.v1"
ANSWER_CHECK = "answer-checks.v1"
CODE_CHECK = "second-look.v1"
NO_CLAUSE_GAP = "No clause of the documents in force was found for this provision on two looks."
REGULATION_NAMES = {"DORA": "DORA", "AI-ACT": "AI Act", "SS1-23": "SS1/23"}
_DISPLAY = {"harbour-mutual-bank": "Harbour Mutual Bank"}
_IN_WORDS = {"DORA": "DORA", "AI-ACT": "the AI Act", "SS1-23": "SS1/23"}
SS123_REASON = (
    "its publisher allows personal and internal use only, so its text and the recordings that "
    "carry it are not held in this repository"
)
"""Why SS1/23 is left out of a run on a clean clone."""
_LEFT_OUT_BY_OPTION = "left out of this run by its --regulations option"
FETCH_COMMAND = "make regulations-check"
RECORDINGS_PLACEHOLDER = "<folder>"


class JudgementRefusedError(ContextError):
    """One or more obligations have no usable answer; the message names each and why."""


class NothingToAssessError(ContextError):
    """No obligation applies to the firm in the texts given, so there is nothing to assess."""


def _named(keys: Iterable[str]) -> str:
    """Name regulations as a sentence does: ``DORA, the AI Act and SS1/23``."""
    names = [_IN_WORDS[k] for k in REGULATION_NAMES if k in set(keys)]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def not_included(corpus: str, texts: TextIndex) -> list[NotIncluded]:
    """Name each regulation of the manifest that the texts do not hold, as the bundle records it.

    Args:
        corpus: The corpus's name, which the commands carry.
        texts: The texts a run reads; a regulation not in them is left out.

    Returns:
        One record per regulation left out, in the order of ``REGULATION_NAMES``: the reason, and
        the commands that fetch its text and that record its calls into a folder of the reader's.
    """
    left = []
    for key in REGULATION_NAMES:
        if key in texts.regulations:
            continue
        record = (
            f"MODEL_BACKEND=record MODEL_RECORDINGS_DIR={RECORDINGS_PLACEHOLDER} "
            f"python -m assessment run {corpus} --regulations {key} "
            f"--out {RECORDINGS_PLACEHOLDER}"
        )
        left.append(
            NotIncluded(
                regulation=key,  # type: ignore[arg-type]
                reason=SS123_REASON if key == "SS1-23" else _LEFT_OUT_BY_OPTION,
                commands=[FETCH_COMMAND, record],
            )
        )
    return left


@dataclass(frozen=True)
class Prepared:
    """Everything a run needs before its first call."""

    texts: TextIndex
    profile: FirmProfile
    register: Register
    graph: list[Fact]
    candidates: list[Candidate]
    kept: dict[str, list[Candidate]]
    judged: list[Obligation]
    by_code: list[Obligation]
    second_look: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class RunPlan:
    """The calls a run will make, counted by code before any is made."""

    obligations: int
    applicable: int
    judged: int
    by_code: int
    second_look: int
    rounds: int
    concurrency: int
    by_regulation: dict[str, int]

    @property
    def line(self) -> str:
        """The plan in words."""
        return (
            f"Plan: {self.applicable} applicable obligations, {self.judged} judgement calls and "
            f"{self.by_code} assessed by code with no call; at {self.concurrency} at a time that "
            f"is about {self.rounds} rounds"
        )


Finder = Callable[..., list[Candidate]]


def prepare(
    texts: TextIndex,
    profile: FirmProfile,
    *,
    finder: Finder = find_candidates,
) -> Prepared:
    """Build the register, the graph and the candidates of both looks, with no model call.

    Args:
        texts: The regulations and the corpus.
        profile: The firm's stated profile.
        finder: Finds candidates, as ``assessment.interfaces.CandidateFinder`` states; tests
            give one that withholds candidates.

    Returns:
        What the plan and the run read.
    """
    register = build_register(texts, profile)
    graph = build_graph(texts)
    first = finder(register, texts, graph, second_look=False)
    left = without_candidates(register, first)
    second: list[Candidate] = []
    if left:
        second = finder(
            register.model_copy(update={"obligations": left}), texts, graph, second_look=True
        )
    candidates = [*first, *second]
    kept: dict[str, list[Candidate]] = {}
    for c in candidates:
        if c.kept:
            kept.setdefault(c.obligation_id, []).append(c)
    applicable = [o for o in register.obligations if o.applies is True]
    return Prepared(
        texts=texts,
        profile=profile,
        register=register,
        graph=graph,
        candidates=candidates,
        kept=kept,
        judged=[o for o in applicable if o.obligation_id in kept],
        by_code=[o for o in applicable if o.obligation_id not in kept],
        second_look=frozenset(o.obligation_id for o in left),
    )


def plan_of(prepared: Prepared, *, concurrency: int = DEFAULT_CONCURRENCY) -> RunPlan:
    """Count the calls of a run.

    Args:
        prepared: The prepared run.
        concurrency: How many calls run at once.

    Returns:
        The plan: one call per applicable obligation with a kept candidate.
    """
    by_regulation = Counter(o.regulation for o in prepared.judged + prepared.by_code)
    ordered = {k: by_regulation[k] for k in REGULATION_NAMES if k in by_regulation}
    return RunPlan(
        obligations=len(prepared.register.obligations),
        applicable=len(prepared.judged) + len(prepared.by_code),
        judged=len(prepared.judged),
        by_code=len(prepared.by_code),
        second_look=len(prepared.second_look),
        rounds=math.ceil(len(prepared.judged) / concurrency),
        concurrency=concurrency,
        by_regulation=ordered,
    )


@dataclass(frozen=True)
class _Outcome:
    obligation: Obligation
    request: JudgementRequest
    answer: JudgementAnswer | None
    tries: int
    failure: str | None


async def _ask(
    judge: AsyncJudge,
    obligation: Obligation,
    request: JudgementRequest,
    texts: TextIndex,
    gate: asyncio.Semaphore,
) -> _Outcome:
    faults: list[str] = []
    for attempt in range(1, MAX_TRIES + 1):
        try:
            async with gate:
                answer = await judge(request, faults=faults)
        except (OSError, ModelError, JudgeReplyError, ValueError) as exc:
            return _Outcome(obligation, request, None, attempt, f"{type(exc).__name__}: {exc}")
        faults = check_answer(answer, request, obligation, texts)
        if not faults:
            return _Outcome(obligation, request, answer, attempt, None)
    return _Outcome(obligation, request, None, MAX_TRIES, "; ".join(faults))


def _tries(count: int) -> str:
    return "try" if count == 1 else "tries"


def _unique(quotes: Sequence[ClauseQuote]) -> list[ClauseQuote]:
    return list({(q.clause.document, q.clause.clause, q.quote): q for q in quotes}.values())


def _point_gaps(points: Sequence[PointJudgement]) -> str:
    return " ".join(f"Point ({p.point}): {p.gap}" for p in points if p.state != "covered" and p.gap)


def _model_assessment(
    prepared: Prepared, outcome: _Outcome, model: str
) -> tuple[Assessment, list[Fact], Judgement]:
    texts = prepared.texts
    o, answer = outcome.obligation, outcome.answer
    assert answer is not None
    order = {p: i for i, p in enumerate(o.points)}
    points = sorted(answer.points, key=lambda p: order.get(p.point, len(order)))
    state: State = derive_state(p.state for p in points) if points else answer.state
    quotes = _unique([*answer.clause_quotes, *(q for p in points for q in p.clause_quotes)])
    gap = None if state == "covered" else (answer.gap or "").strip() or _point_gaps(points)
    source_id = texts.regulation_source(o.regulation).id
    facts = [
        make_fact(
            texts,
            kind="provision",
            source_id=source_id,
            anchor=o.anchor,
            quote=answer.provision_quote,
            obligation_id=o.obligation_id,
        )
    ]
    facts += [
        make_fact(
            texts,
            kind="clause",
            source_id=texts.source(q.clause.document).id,
            anchor=q.clause.anchor,
            quote=q.quote,
            obligation_id=o.obligation_id,
        )
        for q in quotes
    ]
    assessment = Assessment.build(
        obligation_id=o.obligation_id,
        regulation=o.regulation,
        state=state,
        provision_quote=answer.provision_quote,
        clause_quotes=quotes,
        gap=gap,
        suggested_wording=None if state == "covered" else answer.suggested_wording,
        points=points,
        second_look=o.obligation_id in prepared.second_look,
        assessed_by="model",
        evidence=[f.id for f in facts],
        checks=[
            CheckResult(
                check=QUOTE_CHECK,
                outcome="pass",
                detail=f"the provision quote and {len(quotes)} clause quote(s) lie word for word "
                "in their texts",
            ),
            CheckResult(
                check=ANSWER_CHECK,
                outcome="pass",
                detail=f"the answer held every plain-code check at try {outcome.tries}",
            ),
        ],
    )
    judgement = Judgement(
        role="assess",
        model=model,
        request_digest=request_digest(outcome.request),
        request=outcome.request,
        answer=answer,
    )
    return assessment, facts, judgement


def _code_assessment(prepared: Prepared, obligation: Obligation) -> tuple[Assessment, list[Fact]]:
    texts = prepared.texts
    quote = lead(obligation.provision_words)
    fact = make_fact(
        texts,
        kind="provision",
        source_id=texts.regulation_source(obligation.regulation).id,
        anchor=obligation.anchor,
        quote=quote,
        obligation_id=obligation.obligation_id,
    )
    points = [
        PointJudgement(point=p, state="not covered", clause_quotes=[], gap=NO_CLAUSE_GAP)
        for p in obligation.points
    ]
    assessment = Assessment.build(
        obligation_id=obligation.obligation_id,
        regulation=obligation.regulation,
        state="not covered",
        provision_quote=quote,
        clause_quotes=[],
        gap=NO_CLAUSE_GAP,
        suggested_wording=None,
        points=points,
        second_look=True,
        assessed_by="code",
        evidence=[fact.id],
        checks=[
            CheckResult(
                check=QUOTE_CHECK,
                outcome="pass",
                detail="the provision quote lies word for word in its unit",
            ),
            CheckResult(
                check=CODE_CHECK,
                outcome="pass",
                detail="no clause was kept on the first look or on the second, so no call was made",
            ),
        ],
    )
    return assessment, [fact]


def _found_state(seed: Seed, register: Register, by_id: dict[str, Assessment]) -> State:
    ref = resolve_provision(seed.regulation, seed.provision)
    targets = [o.obligation_id for o in match_seed(seed, register)]
    if len(targets) == 1:
        assessment = by_id[targets[0]]
        point = next((p for p in assessment.points if ref.points[:1] == (p.point,)), None)
        return point.state if point else assessment.state
    return derive_state(by_id[t].state for t in targets)


def _seed_matches(
    seeds: Sequence[Seed], register: Register, by_id: dict[str, Assessment]
) -> list[SeedMatch]:
    matches = []
    for seed in seeds:
        targets = [o.obligation_id for o in match_seed(seed, register)]
        missing = [t for t in targets if t not in by_id]
        if not targets or missing:
            raise JudgementRefusedError(
                f"The seed {seed.seed_id} ({seed.provision}) has no assessed obligation at its "
                f"place: found {targets}, not assessed {missing}."
            )
        ref = resolve_provision(seed.regulation, seed.provision)
        matches.append(
            SeedMatch(
                seed_id=seed.seed_id,
                regulation=seed.regulation,  # type: ignore[arg-type]
                target=ref.anchor,
                points=list(ref.points),
                obligation_ids=targets,
                found_state=_found_state(seed, register, by_id),
                seeded_state=seed.state,
                cited_clauses=[q.clause for t in targets for q in by_id[t].clause_quotes],
                seeded_clauses=[ClauseRef(document=d, clause=c) for d, c in seed.clauses],
            )
        )
    return matches


def _clause_map(prepared: Prepared, assessments: Sequence[Assessment]) -> list[ClauseMapping]:
    texts = prepared.texts
    quoted: dict[tuple[str, str], list[str]] = {}
    for a in assessments:
        for q in a.clause_quotes:
            ids = quoted.setdefault((q.clause.document, q.clause.clause), [])
            if a.obligation_id not in ids:
                ids.append(a.obligation_id)
    considered = Counter(
        (c.clause.document, c.clause.clause) for c in prepared.candidates if c.kept
    )
    mappings = []
    for document, clauses in texts.clauses.items():
        if not texts.in_force(document):
            continue
        for clause in clauses:
            key = (document, clause.number)
            if key in quoted:
                reason = None
            elif considered[key]:
                reason = (
                    f"found as a candidate for {considered[key]} obligation(s) and quoted by "
                    "none of their assessments"
                )
            else:
                reason = (
                    "found as a candidate for no applicable obligation of "
                    f"{_named(texts.regulations)}"
                )
            mappings.append(
                ClauseMapping(
                    clause=ClauseRef(document=document, clause=clause.number),
                    obligations=quoted.get(key, []),
                    unmapped_reason=reason,
                )
            )
    return mappings


def _gap_report(
    prepared: Prepared, assessments: Sequence[Assessment], *, model: str, sources: list[str]
) -> Brief:
    register = prepared.register
    statements = []
    for a in assessments:
        obligation = register.obligation(a.obligation_id)
        if a.state == "covered" or obligation is None:
            continue
        name = REGULATION_NAMES[a.regulation]
        statements.append(
            Statement.build(
                heading=name,
                text=f"{name} {obligation.label}, {a.state}: {a.gap}",
                cites=a.evidence,
            )
        )
    if not statements:
        if not assessments:
            raise NothingToAssessError(
                f"No obligation of {register.corpus} applies to the firm in the texts read, so "
                "there is nothing to assess and no gap report to write."
            )
        first = assessments[0]
        statements.append(
            Statement.build(
                heading=REGULATION_NAMES[first.regulation],
                text="Every applicable provision is stated as covered by the documents in force.",
                cites=first.evidence,
            )
        )
    institution = _DISPLAY.get(register.corpus, register.corpus)
    return Brief.build(
        request=(
            f"Gap report of the {institution} policy set against "
            f"{_named(register.regulation_digests)}"
        ),
        sources=sources,
        statements=statements,
        open_question_ids=[],
        model=model,
        prompt_version=PROMPT_VERSION,
    )


async def assess_async(
    prepared: Prepared,
    judge: AsyncJudge,
    *,
    run: str,
    concurrency: int = DEFAULT_CONCURRENCY,
    seeds: Sequence[Seed] = (),
) -> Bundle:
    """Make the calls and assemble the bundle, which is not yet checked as a whole.

    Args:
        prepared: The prepared run.
        judge: Makes the one call per obligation.
        run: ``record`` or ``replay``, as the model backend says.
        concurrency: How many calls run at once.
        seeds: The corpus's seeded cases, matched at the end; none for a corpus with none.

    Returns:
        The bundle, assessments in register order whatever order the calls finished in.

    Raises:
        JudgementRefusedError: If any obligation has no usable answer; every obligation is asked
            first, so a rerun in record mode needs only the calls that failed.
        NothingToAssessError: If no obligation applies to the firm.
    """
    texts = prepared.texts
    terms = definitions(texts)
    gate = asyncio.Semaphore(concurrency)
    jobs = [
        _ask(judge, o, make_request(o, prepared.kept[o.obligation_id], texts, terms), texts, gate)
        for o in prepared.judged
    ]
    outcomes = await asyncio.gather(*jobs)
    failed = [o for o in outcomes if o.failure is not None]
    if failed:
        lines = [
            f"- {o.obligation.obligation_id} (after {o.tries} {_tries(o.tries)}: {o.failure})"
            for o in failed
        ]
        raise JudgementRefusedError(
            "\n".join(
                [f"{len(failed)} of {len(outcomes)} obligations have no usable answer:", *lines]
            )
        )
    done = {o.obligation.obligation_id: o for o in outcomes}
    code = {o.obligation_id: o for o in prepared.by_code}
    assessments: list[Assessment] = []
    judgements: list[Judgement] = []
    facts: list[Fact] = []
    for o in prepared.register.obligations:
        if o.obligation_id in done:
            assessment, made, judgement = _model_assessment(
                prepared, done[o.obligation_id], judge.model_name
            )
            judgements.append(judgement)
        elif o.obligation_id in code:
            assessment, made = _code_assessment(prepared, o)
        else:
            continue
        assessments.append(assessment)
        facts.extend(made)
    facts = list({f.id: f for f in [*facts, *prepared.graph]}.values())
    by_id = {a.obligation_id: a for a in assessments}
    sources = [r.source.id for r in texts.regulations.values()]
    sources += [d.source.id for d in texts.corpus.documents]
    retried = sum(o.tries - 1 for o in outcomes)
    counts = {
        "obligations": len(prepared.register.obligations),
        "applicable": len(assessments),
        "judgements": len(judgements),
        "assessed by code": len(code),
        "retried calls": retried,
        "candidates": len(prepared.candidates),
        "graph links": len(prepared.graph),
        "facts": len(facts),
    }
    return Bundle(
        index=BundleIndex(
            corpus=prepared.register.corpus,
            run=run,  # type: ignore[arg-type]
            scope=[],
            instructions_digest=(
                getattr(judge, "instructions_digest", None) or digest_of(load_instructions())
            ),
            not_included=not_included(prepared.register.corpus, texts),
            source_ids=sources,
            counts=counts,
        ),
        obligation_register=prepared.register,
        candidates=prepared.candidates,
        judgements=judgements,
        assessments=assessments,
        facts=facts,
        clause_map=_clause_map(prepared, assessments),
        seed_matches=_seed_matches(seeds, prepared.register, by_id),
        gap_report=_gap_report(prepared, assessments, model=judge.model_name, sources=sources),
    )


def run_assessment(
    corpus: str,
    judge: AsyncJudge,
    *,
    texts: TextIndex | None = None,
    prepared: Prepared | None = None,
    run: str = "record",
    concurrency: int = DEFAULT_CONCURRENCY,
    seeds: Sequence[Seed] | None = None,
) -> Bundle:
    """Run the whole assessment of one corpus and return its bundle, checked.

    Args:
        corpus: The corpus's name.
        judge: Makes the one call per obligation.
        texts: The texts, read when not given.
        prepared: The prepared run, built when not given.
        run: ``record`` or ``replay``.
        concurrency: How many calls run at once.
        seeds: The seeded cases to match; the Harbour Mutual Bank seeds for that corpus, none
            for any other, when not given. Only the seeds of the regulations the texts hold are
            matched.

    Returns:
        The bundle, after every plain-code check passed.

    Raises:
        JudgementRefusedError: If an obligation has no usable answer.
        assessment.validate.BundleInvalidError: If the assembled bundle fails a check.
    """
    if prepared is None:
        read = texts or load_texts(corpus)
        prepared = prepare(read, load_profile(corpus))
    chosen = (
        seeds if seeds is not None else (load_seeds() if corpus == "harbour-mutual-bank" else [])
    )
    chosen = [s for s in chosen if s.regulation in prepared.texts.regulations]
    bundle = asyncio.run(
        assess_async(prepared, judge, run=run, concurrency=concurrency, seeds=chosen)
    )
    require_valid(bundle, prepared.texts)
    return bundle
