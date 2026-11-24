"""The planted invalid examples: each a valid example with one fault put in.

Where the fault is not in the fields an id is derived from, the id is recomputed, so the
validator must catch the plant for the declared reason and no other.
"""

from __future__ import annotations

import copy
from typing import Any

from fsi_common.examples.data import COPIED_ATTRIBUTES, Examples
from fsi_common.ids import DIGEST_PREFIX, ID_HEX_LENGTH, content_id, digest_json
from fsi_common.records import RECORD_TYPES, Brief, Fact, Source, Statement, fact_id_basis

Json = dict[str, Any]


def rehash(data: Json) -> Json:
    """Recompute the id (and a brief's digest) of a JSON record after a fault was put in.

    Args:
        data: A record's JSON, with every field present.

    Returns:
        The same JSON with its derived fields recomputed.
    """
    record_type = RECORD_TYPES[data["schema"]]
    if record_type is Source:
        data["id"] = content_id("source", {k: data[k] for k in ("kind", "key", "digest")})
        return data
    if record_type is Fact:
        data["id"] = content_id(Fact.ID_PREFIX, fact_id_basis(data, COPIED_ATTRIBUTES))
        return data
    if record_type is Brief:
        for statement in data["statements"]:
            basis = {k: v for k, v in statement.items() if k != "id"}
            statement["id"] = content_id(Statement.ID_PREFIX, basis)
    excluded = record_type.ID_EXCLUDES | {"schema"}
    basis = {k: v for k, v in data.items() if k not in excluded}
    if record_type is Brief:
        data["content_digest"] = digest_json(basis)
        data["id"] = "brief:" + data["content_digest"][len(DIGEST_PREFIX) :][:ID_HEX_LENGTH]
    else:
        data["id"] = content_id(record_type.ID_PREFIX, basis)
    return data


def valid_files(ex: Examples) -> dict[str, Any]:
    """Return each valid example file with its JSON.

    Args:
        ex: The valid examples.

    Returns:
        One file per record type, a second fact and a decision answering a question, the bundle
        that holds a whole run's records together, the same bundle after a rerun whose model
        prompt, extractor and check wording moved (the decision carries), and two contents of
        one fact kept side by side by a disagreement.
    """
    bundle = [
        ex.document,
        ex.firms,
        ex.providers,
        ex.unit_7_1,
        ex.unit_9_3,
        ex.unit_firm,
        ex.unit_provider,
        ex.fact_7_1,
        ex.fact_9_3,
        ex.fact_notes,
        ex.fact_service,
        ex.fact_small_firm,
        ex.question,
        ex.disagreement,
        ex.accept_7_1,
        ex.brief,
        ex.sign_off,
        ex.firms_accounting,
    ]
    singles = {
        "source.json": ex.document,
        "source_unit.json": ex.unit_7_1,
        "fact.json": ex.fact_7_1,
        "fact-inferred.json": ex.fact_small_firm,
        "open_question.json": ex.question,
        "disagreement.json": ex.disagreement,
        "decision.json": ex.accept_7_1,
        "decision-answer.json": ex.answer,
        "brief.json": ex.brief,
        "signoff.json": ex.sign_off,
        "unit_accounting.json": ex.document_accounting,
    }
    files: dict[str, Any] = {name: record.to_json() for name, record in singles.items()}
    files["bundle.json"] = [record.to_json() for record in bundle]
    rerun = [ex.fact_7_1_rerun if record is ex.fact_7_1 else record for record in bundle]
    files["bundle-rerun.json"] = [record.to_json() for record in rerun]
    variants = [
        ex.document,
        ex.unit_7_1,
        ex.fact_7_1,
        ex.fact_7_1_variant,
        ex.variant_disagreement,
    ]
    files["bundle-fact-variants.json"] = [record.to_json() for record in variants]
    return files


def _plant(record: Json, change: Any, *, keep_id: bool = False) -> Json:
    data = copy.deepcopy(record)
    change(data)
    return data if keep_id else rehash(data)


def _bundle_plant(ex: Examples, change: Any) -> list[Json]:
    bundle = copy.deepcopy(valid_files(ex)["bundle.json"])
    change(bundle)
    return bundle


def planted_files(ex: Examples) -> dict[str, tuple[Any, str, str]]:
    """Return each planted file with its content, its declared check and its declared reason.

    Args:
        ex: The valid examples the faults are put into.

    Returns:
        A mapping from file name to the file's JSON, the check that must catch it and why.
    """
    fact, decision, brief = ex.fact_7_1.to_json(), ex.accept_7_1.to_json(), ex.brief.to_json()
    sign_off, question = ex.sign_off.to_json(), ex.question.to_json()
    accounting = ex.document_accounting.to_json()

    def by_schema(bundle: list[Json], schema: str) -> Json:
        return next(item for item in bundle if item["schema"] == schema)

    def stale_check(bundle: list[Json]) -> None:
        target = next(item for item in bundle if item["id"] == ex.fact_7_1.id)
        target["attributes"]["requirement"] = "Tell the FSOA about a major incident"

    def failed_check(bundle: list[Json]) -> None:
        target = next(item for item in bundle if item["id"] == ex.fact_9_3.id)
        target["checks"][1] = {
            "check": "deadline-verbatim.v1",
            "outcome": "fail",
            "detail": "the deadline is not in paragraph 9.3",
        }

    def cites_missing(bundle: list[Json]) -> None:
        planted_brief = by_schema(bundle, "brief.v1")
        planted_brief["statements"][0]["cites"] = ["fact:0123456789abcdef"]
        rehash(planted_brief)
        signed = by_schema(bundle, "signoff.v1")
        signed.update(brief_id=planted_brief["id"], brief_digest=planted_brief["content_digest"])
        rehash(signed)

    def unrecorded(bundle: list[Json]) -> None:
        signed = by_schema(bundle, "signoff.v1")
        signed["assumptions"] = []
        rehash(signed)

    def digest_differs(bundle: list[Json]) -> None:
        signed = by_schema(bundle, "signoff.v1")
        signed["brief_digest"] = DIGEST_PREFIX + "0" * 64
        rehash(signed)

    def accounting_mismatch(bundle: list[Json]) -> None:
        listed = by_schema(bundle, "unit_accounting.v1")
        listed.update(units_in=1, with_facts=["row:FIRM-002"])
        rehash(listed)

    def duplicate_id(bundle: list[Json]) -> None:
        bundle.append(ex.document.to_json() | {"title": "Policy Statement PS26/4, second copy"})

    def variant_alone(bundle: list[Json]) -> None:
        bundle.append(ex.fact_7_1_variant.to_json())

    def claim_digest_unresolved(bundle: list[Json]) -> None:
        listed = by_schema(bundle, "disagreement.v1")
        listed["claims"][0]["judged_digest"] = DIGEST_PREFIX + "0" * 64
        rehash(listed)

    def decision_not_about_it(bundle: list[Json]) -> None:
        by_schema(bundle, "open_question.v1").update(state="answered", decision_id=ex.accept_7_1.id)

    small_firm = ex.fact_small_firm.to_json()
    rule = small_firm["status"]["rule"]
    return {
        "schema-unknown.json": (
            {"schema": "verdict.v1", "id": "verdict:0123456789abcdef"},
            "schema.unknown",
            "a record whose schema this package does not define",
        ),
        "accounting-count-as-text.json": (
            _plant(accounting, lambda d: d.update(units_in="48")),
            "schema.type",
            "a count written as text",
        ),
        "fact-provenance-other-unit.json": (
            _plant(fact, lambda d: d["provenance"].update(anchor="para:7.2")),
            "fact.provenance-subject",
            "a fact whose provenance names another paragraph",
        ),
        "fact-observed-without-date.json": (
            _plant(
                fact,
                lambda d: d.update(
                    status={
                        "status": "observed",
                        "observed_at": None,
                        "rule": None,
                        "unknown_reason": None,
                    }
                ),
            ),
            "status.observed",
            "an observed fact that does not say when it was read",
        ),
        "fact-unknown-without-reason.json": (
            _plant(
                fact,
                lambda d: d.update(
                    status={
                        "status": "unknown",
                        "observed_at": None,
                        "rule": None,
                        "unknown_reason": None,
                    }
                ),
            ),
            "status.unknown",
            "an unknown fact that does not say why",
        ),
        "fact-documented-with-rule.json": (
            _plant(fact, lambda d: d["status"].update(rule=rule)),
            "status.extra",
            "a documented fact carrying an inference rule",
        ),
        "fact-match-rate-above-population.json": (
            _plant(
                small_firm,
                lambda d: d["status"]["rule"].update(match_rate={"matched": 2, "population": 1}),
            ),
            "status.match-rate",
            "a rule said to match 2 cases of 1",
        ),
        "question-cites-nothing.json": (
            _plant(question, lambda d: d.update(cites=[])),
            "question.cites",
            "a question about missing data that cites nothing",
        ),
        "disagreement-reconciled-without-decision.json": (
            _plant(ex.disagreement.to_json(), lambda d: d.update(status="reconciled")),
            "disagreement.status",
            "a disagreement marked reconciled with no person's decision",
        ),
        "signoff-returned-without-reason.json": (
            _plant(sign_off, lambda d: d.update(outcome="returned")),
            "signoff.reason",
            "a returned brief with no reason",
        ),
        "signoff-assumption-twice.json": (
            _plant(sign_off, lambda d: d.update(assumptions=d["assumptions"] * 2)),
            "signoff.assumptions",
            "the same question accepted as an assumption twice",
        ),
        "bundle-id-duplicate.json": (
            _bundle_plant(ex, duplicate_id),
            "id.duplicate",
            "two different sources under one id",
        ),
        "bundle-question-decision-not-about-it.json": (
            _bundle_plant(ex, decision_not_about_it),
            "question.decision-matches",
            "a question marked answered by a decision about a fact",
        ),
        "source-missing-digest.json": (
            _plant(ex.document.to_json(), lambda d: d.pop("digest"), keep_id=True),
            "schema.required",
            "a source with no digest of its bytes",
        ),
        "fact-no-quote.json": (
            _plant(fact, lambda d: d.update(quote="  ")),
            "fact.quote",
            "a fact with no quote",
        ),
        "fact-id-does-not-recompute.json": (
            _plant(fact, lambda d: d.update(quote=d["quote"] + " and"), keep_id=True),
            "id.recompute",
            "the quote was changed after the id was derived",
        ),
        "fact-kind-not-listed.json": (
            _plant(fact, lambda d: d.update(kind="recommendation")),
            "fact.kind",
            "a kind outside the topic's list",
        ),
        "fact-accepted-by-machine.json": (
            _plant(fact, lambda d: d.update(accepted=True)),
            "schema.extra",
            "a fact carrying an accepted state, which no record type allows",
        ),
        "fact-model-without-prompt.json": (
            _plant(fact, lambda d: d["provenance"].update(prompt_version=None)),
            "provenance.model-pair",
            "a model-produced fact with no prompt version",
        ),
        "fact-inferred-without-rule.json": (
            _plant(ex.fact_small_firm.to_json(), lambda d: d["status"].update(rule=None)),
            "status.inferred",
            "an inferred fact that names no rule",
        ),
        "decision-empty-reviewer.json": (
            _plant(decision, lambda d: d["reviewer"].update(name="")),
            "person.empty",
            "a decision with an empty reviewer",
        ),
        "decision-model-reviewer.json": (
            _plant(decision, lambda d: d["reviewer"].update(name="claude-sonnet-5-5")),
            "person.machine",
            "a decision whose reviewer is a model",
        ),
        "decision-system-role.json": (
            _plant(decision, lambda d: d["reviewer"].update(role="system")),
            "person.machine",
            "a decision whose reviewer's role is the system",
        ),
        "decision-judged-digest-does-not-recompute.json": (
            _plant(decision, lambda d: d.update(judged_digest=digest_json("another fact"))),
            "decision.judged-digest",
            "a decision whose judged digest is not that of what it says was judged",
        ),
        "decision-claude-alone-reviewer.json": (
            _plant(decision, lambda d: d["reviewer"].update(name=" claude ")),
            "person.machine",
            "a decision whose reviewer's whole name is a model's",
        ),
        "fact-deadline-changed-after-id.json": (
            _plant(
                fact,
                lambda d: d["attributes"].update(deadline="within 24 hours"),
                keep_id=True,
            ),
            "id.recompute",
            "the deadline as written was changed after the id was derived",
        ),
        "bundle-fact-variant-without-disagreement.json": (
            _bundle_plant(ex, variant_alone),
            "id.duplicate",
            "two contents of one fact with no disagreement keeping them side by side",
        ),
        "bundle-disagreement-claim-not-held.json": (
            _bundle_plant(ex, claim_digest_unresolved),
            "ref.resolves",
            "a disagreement naming a fact by a judged digest no fact in the bundle has",
        ),
        "decision-answer-on-fact.json": (
            _plant(decision, lambda d: d.update(outcome="answer", answer="Yes")),
            "decision.outcome",
            "an answer given to a fact, which is not a question",
        ),
        "decision-date-not-a-date.json": (
            _plant(decision, lambda d: d.update(date="2026-02-30")),
            "schema.date",
            "a date that is not in the calendar",
        ),
        "signoff-no-digest.json": (
            _plant(sign_off, lambda d: d.pop("brief_digest")),
            "schema.required",
            "a sign-off with no digest",
        ),
        "question-reason-not-listed.json": (
            _plant(question, lambda d: d.update(reason="model_unsure")),
            "schema.enum",
            "an open question whose reason is outside the closed list",
        ),
        "question-accepted-without-decision.json": (
            _plant(question, lambda d: d.update(state="accepted")),
            "question.state",
            "a question marked accepted with no person's decision",
        ),
        "disagreement-one-claim.json": (
            _plant(ex.disagreement.to_json(), lambda d: d.update(claims=d["claims"][:1])),
            "disagreement.claims",
            "a disagreement holding one fact",
        ),
        "brief-statement-cites-nothing.json": (
            _plant(brief, lambda d: d["statements"][0].update(cites=[])),
            "brief.statement-cites",
            "a brief statement citing no fact",
        ),
        "brief-statement-edited.json": (
            _plant(
                brief,
                lambda d: d["statements"][1].update(text="Contracts may wait until 2029."),
                keep_id=True,
            ),
            "id.recompute",
            "a statement edited after its id and the brief's digest were derived",
        ),
        "brief-digest-does-not-recompute.json": (
            _plant(
                brief, lambda d: d.update(content_digest=digest_json("another brief")), keep_id=True
            ),
            "digest.recompute",
            "a brief carrying a digest of other content",
        ),
        "accounting-does-not-close.json": (
            _plant(accounting, lambda d: d.update(with_facts=d["with_facts"][:-2])),
            "accounting.closes",
            "48 units in, 45 with facts and 1 without",
        ),
        "accounting-empty.json": (
            _plant(accounting, lambda d: d.update(units_in=0, with_facts=[], without_facts=[])),
            "accounting.empty",
            "a source read into no units",
        ),
        "bundle-decision-digest-stale.json": (
            _bundle_plant(ex, stale_check),
            "decision.digest-stale",
            "a fact changed after the reviewer decided on it",
        ),
        "bundle-brief-cites-failed-check.json": (
            _bundle_plant(ex, failed_check),
            "brief.cites-failed-check",
            "a statement citing a fact whose deadline check failed",
        ),
        "bundle-statement-cites-missing-fact.json": (
            _bundle_plant(ex, cites_missing),
            "ref.resolves",
            "a statement citing a fact that is not there",
        ),
        "bundle-signoff-digest-differs.json": (
            _bundle_plant(ex, digest_differs),
            "signoff.digest-matches",
            "a sign-off against a digest other than the brief's",
        ),
        "bundle-open-question-unrecorded.json": (
            _bundle_plant(ex, unrecorded),
            "signoff.open-question-unrecorded",
            "a signed brief whose open question is neither settled nor accepted as an assumption",
        ),
        "bundle-accounting-facts-mismatch.json": (
            _bundle_plant(ex, accounting_mismatch),
            "accounting.facts-match",
            "accounting that lists a unit with facts when the facts cite another",
        ),
    }
