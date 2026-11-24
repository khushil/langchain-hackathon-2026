# fsi_common

`fsi_common` is the shared member of this workspace. It holds the record types every topic writes and reads:
what was read, what it says, what is still open, and what a named person decided about it. Nothing in it
assumes a regulatory document. A fact is about a source unit, named by its source's id and an anchor in that
source's own identifiers, so the same records serve a policy statement, a customer's application or a stream of
card transactions.

## The records

Each record type is a Pydantic model in `fsi_common/records/`, exported as a JSON Schema to
`fsi_common/schemas/<name>.v1.schema.json`. Every record's JSON carries its schema name in `schema`.

| Record | Schema | What it holds |
| --- | --- | --- |
| Source | `source.v1` | One thing that was read: its own key (`PS26-4`), title, kind, the digest of its bytes, where it was read from and the terms on which it may be reused. |
| Source unit | `source_unit.v1` | One place in a source that a fact can cite, such as `para:7.1` or `row:FIRM-001`, with the digest of its text. |
| Fact | `fact.v1` | One thing a source unit says, with a word-for-word quote, normalised attributes, how it is known (documented, observed, inferred by a named rule with its match rate, or unknown with the reason), where it came from (the extractor, and the model and prompt version where a model produced it) and the result of each plain-code check run on it. Its kind comes from the topic's closed list. |
| Open question | `open_question.v1` | Something the sources do not settle, written as a question one role can answer: why it is unknown, what changes with the answer, whom to ask, a reason from a closed list, what it cites, a priority that orders the review and never removes a question, and where it stands. |
| Disagreement | `disagreement.v1` | Two or more facts that differ about one thing, kept side by side. The record has no field that picks a winner; a person reconciles it with a decision. |
| Decision | `decision.v1` | One person's accept, amend or reject on a fact, a statement or a disagreement, or their answer to an open question, with the digest of the whole record they saw, what they judged in it and its digest, their reason in their own words, their name and role, and the date. |
| Brief | `brief.v1` | The statements written for one request, each citing one or more facts, the open questions carried to the reviewer, the digest of all of that, and the model and prompt version that wrote it. |
| Sign-off | `signoff.v1` | A person's signature on a brief, or its return, at the digest they read, with each open question they accept as an assumption in their own words. |
| Unit accounting | `unit_accounting.v1` | For one source, the units read, the units that produced facts and the units that produced none with the reason. The two lists must add up to the units read. |

## Ids and digests

Every id is the record's family, a colon and the first 16 hex characters of the SHA-256 of the canonical JSON of
its content (`fact:9ff827e1365632d7`), never a clock, a counter or a position. A fact's id comes from its kind,
subject, quote and the attributes its topic declares as copied word for word from the source (for the compliance
brief, the deadline as written), so a rerun that finds the same obligation gives it the same id however a model
words its requirement, and a reviewer's earlier decision still attaches to it. A brief's id is the start of its
content digest. `Record.build(...)` derives the id; reading a record checks that it recomputes.

## The rules a record cannot break

A reviewer is always a named person. A decision or a sign-off whose reviewer's name or role is empty, or names a
model, a program or the system (`claude-sonnet-5-5`, `System`), is refused, by the Pydantic models and by the
JSON Schemas alone. No record type has a field through which the machine could mark anything accepted. An open
question moves to answered, accepted or closed with no answer only with the decision that settled it. A
statement of a brief cites at least one fact. A fact always quotes its unit.

## The validator

```bash
cd fsi_common
python -m fsi_common.validate path/to/records/ --fact-kinds path/to/kinds.json --copied-attributes path/to/copied.json
python -m fsi_common.validate --selftest
```

A `.json` file with one object is one record; a `.json` file with an array is a bundle, whose records are also
checked against each other (every cited id is present, each decision's judged digest is its subject's, a signed brief's
open questions are settled or accepted as assumptions, no statement cites a fact that failed a check, and the
unit accounting matches the facts); a `.jsonl` file holds one record per line. The validator prints one line per
check with PASS or FAIL and how many records or bundles it examined, and exits non-zero on any failure, on a file
it cannot read, and when it checked nothing.

`--selftest` validates the examples in `fsi_common/examples/valid/` against the models and the JSON Schemas, then
runs every file in `fsi_common/examples/planted/`: each is a valid example with one fault put in, and
`expected-errors.json` names the check that must catch it and why. The self-test fails if any plant is missed,
is caught by a different check as well, or if any check has no plant. `python -m fsi_common.examples.build`
rebuilds the examples and `python -m fsi_common.export_schemas` the schemas; both have a `--check` mode, which
`make gate` runs.

The examples use the starter's fictional policy statement and firm tables; the reviewer in them and her
decisions are invented.

## The model adapter

`fsi_common.model` is the chat model every agent of the repository runs on. Each call is one isolated, capped run of headless Claude Code (`claude -p`) on the signed-in account, with no tools of its own, no connectors and none of the user's files or settings; the adapter reads each call's start event and refuses the answer if anything else was loaded. At most four calls run at once across the process. A call can be recorded to a folder and replayed from it: a recording is named by the SHA-256 of its request (`request_sha256`), and replay answers a request with no recording by failing by name, never by inventing an answer. `MODEL_BACKEND` chooses between `replay`, `claude-code`, `record` and `langchain`; the repository README describes each.

## The evaluation runner

`fsi_common.evals` holds the pieces of measuring a topic that do not depend on the topic: a measure (a key, a numerator, a denominator and the population counted), a runner that applies code evaluators to pairs of a reference example and an output, and an upload of a dataset to LangSmith that runs once and refuses to change on a rerun. A denominator of zero is reported as "none in scope". Topic 03's measures are in `03_document_summary_agent/evals/`.

## The application

`fsi_common.app` is the shell of the reviewer's application, Review desk. It serves the home page, About, sign-in and sign-out, and mounts every topic folder that holds a `review_app/plugin.py` at the topic's own address. A person signs in by typing a name and a role; a name or role that is empty or names a model, a program or a service is refused. Each page opens with one sentence and at most three tiles, built from the same counts. `make serve` starts it, and `docs/user-guide.md` at the repository root walks through it.

## How the compliance brief uses it

The context layer of topic 03 reads PS26-4 into one source with a unit for each of its 48 paragraphs, and the firm and provider tables into a unit for each row. A run on one section accounts for that section's paragraphs, 5 of them for section 7. Each obligation that a section's sub-agent returns becomes a fact anchored on its paragraph and quoting its evidence, with the starter's `SectionSummary` as the sub-agent's output shape. Plain code records on each fact whether its quote and its deadline are found word for word in the paragraph. Every unit ends with a fact or on a list of units that hold none, each with its reason, and a run stops when the counts do not close. An obligation that cites a paragraph the section does not have becomes an open question for a named role. The brief cites only facts that passed their checks. The reviewer's decisions and sign-off are kept in the LangGraph store under the firm and the document, so a rerun on the same firm and document finds them, and a decision is carried only while the fact it judged is unchanged.

## How a KYC application would use it

Each application would be a source, and each of its fields a unit (`field:CUST-001/date_of_birth`). A sanctions
or PEP screening match would be a fact citing the field it matched, with the matching rule and its measured match
rate on the fact's status. A partial name match would be an open question for the compliance officer, the
officer's risk decision a decision record, and the decision memo a brief with a sign-off.

## How a transaction stream would use it

The stream would be a source and each transaction a unit (`tx:TX-1003`). Each alert would be a fact citing its
transaction, with the rule or score that raised it. A transaction the agent cannot place would be an open
question for the analyst, and the analyst's approve or block answer a decision record. The unit accounting would
show every transaction in the stream as alerted or cleared with a reason.
