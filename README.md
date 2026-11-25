# Compliance brief workflow

This repository builds the compliance brief topic of the FSI hackathon starter. A compliance analyst asks for a brief on a regulatory document for one firm. The workflow reads the document into facts, each citing a paragraph with a word-for-word quote, checks every quote and deadline with plain code, and writes a brief whose statements cite those facts. A named reviewer then opens each statement's source paragraph, accepts, amends or rejects each fact in their own words, and signs the brief or returns it. Nothing in the product can approve a brief on a person's behalf.

The document is the starter's fictional policy statement PS26/4 and the firm is its fictional Harbour Mutual Bank. The repository follows the starter's shape: one folder per topic in a single uv workspace, plus a shared member, `fsi_common`.

## Layout

| Folder | What it holds | State |
| --- | --- | --- |
| `fsi_common/` | The record types (sources, source units, facts, open questions, disagreements, decisions, briefs, sign-offs, unit accounting) with their JSON Schemas, examples and validator; the chat model that calls headless Claude Code and records or replays calls; the evaluation runner; the reviewer's application | Built |
| `03_document_summary_agent/` | The compliance brief topic: the starter's deep agent and section sub-agent, the context layer, the workflow, the evaluations, the application's plug-in, the saved model calls and the notebook | Built |
| `01_kyc_agent/` | The starter's KYC onboarding topic | A README only |
| `02_transaction_monitoring_agent/` | The starter's transaction monitoring topic | A README only |

`docs/user-guide.md` walks through the reviewer's application step by step. `agents.py` in topic 03 gathers every agent of the topic by name, as the hackathon's submission rules ask.

## Setup

You need Python 3.11 or later and [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync --all-packages
cp .env.example .env
```

`.env` holds references to your shell environment and no key. The comments in `.env.example` describe each setting.

LangSmith tracing is on in `.env.example`. With tracing on and no LangSmith key in your shell, importing an agent stops with `TracingKeyMissingError` and a sentence that names both ways out: export `LANGSMITH_KEY` in your shell before you start, or set `LANGSMITH_TRACING=false` in `.env`. Every `make` target runs with tracing off.

The tests of the application drive a headless Chromium through Playwright, and `make gate` fails when none can start. Set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to a Chromium binary if Playwright has none of its own.

`make` uses `.venv/bin/python`, which `uv sync` makes. Name another interpreter with `make gate PYTHON=/path/to/python`.

## Running it with and without Claude Code

`MODEL_BACKEND` in `.env` chooses where the agents' model calls go.

| Value | What happens |
| --- | --- |
| `replay` (the default) | Calls are answered from the 26 saved calls in `03_document_summary_agent/recordings/`. A request with no recording fails by name; replay never invents an answer. |
| `claude-code` | Each call runs headless Claude Code on your signed-in account, with no tools and no access to your connectors, files or settings. The adapter reads every call's start event and refuses the answer if anything else was loaded. No provider key is needed. |
| `record` | As `claude-code`, and each call is also saved to the recordings folder. |
| `langchain` | The starter's route: `init_chat_model(MODEL_NAME)` with a provider key of your own, as `provider:model`. |

`03_document_summary_agent/utils/models.py` is the one place a model is chosen, by the role of the call: the main agent and the brief writer on Opus, each section's sub-agent on Sonnet. The saved calls cover the starter's agent and this repository's workflow, each on the whole of PS26-4, which are the two runs the notebook and the application make. Any other request needs `claude-code`.

To run the starter's agent from `03_document_summary_agent`, on the saved calls:

```bash
LANGSMITH_TRACING=false PYTHONPATH=.:../fsi_common python run_agent.py
```

where `run_agent.py` is a file you save in that folder with this content:

```python
from agent import agent

result = agent.invoke(
    {"messages": [{"role": "user", "content": "Summarise document PS26-4 for FIRM-001"}]}
)
print(result["messages"][-1].text)
```

It prints a brief that begins `# PS26/4 brief for Harbour Mutual Bank (FIRM-001)`.

## The notebook

`03_document_summary_agent/modules/01_document_summary_agent.ipynb` has 37 cells. The first 23 are the starter's notebook, changed only where a model is chosen, which now goes through `get_model`. The 14 after them add four things: the starter's section summaries scored against the reference labels, the same document read into cited facts, the same scoring of this repository's engine over all ten sections beside the starter's, and the place where a person signs. The notebook keeps its outputs from a run on the saved calls.

```bash
make notebook
```

runs it top to bottom on the saved calls with no key and no live call, and ends with all its tests passing. `make gate` includes it.

## The reviewer's application

```bash
make serve
```

starts the application on `APP_HOST` and `APP_PORT`. Without them it listens on every interface of the machine, on the port the comment above the `serve` target in the `Makefile` names. To keep it to your own machine, start it as `APP_HOST=127.0.0.1 APP_PORT=4821 make serve`, which prints `Uvicorn running on http://127.0.0.1:4821 (Press CTRL+C to quit)`, and open that address. Add `PYTHON=/path/to/python` when you did not use `uv sync`.

With `MODEL_BACKEND` at its default of `replay`, the application can only start a brief that has saved calls, which is the whole of PS26-4, all ten sections, for Harbour Mutual Bank; a brief on part of the document stops with the reason "No saved answer is held for part of this brief, so it could not be written here." With `MODEL_BACKEND=claude-code` in `.env`, any sections or the whole document can be started and each brief's model calls run on headless Claude Code.

The application is called Review desk. Its pages are the home page, About, sign-in, and for the compliance brief topic the list of briefs with the form that starts one, the review page, the facts table and the page of a signed or returned brief. About says what the data is. `make serve` keeps the runs, decisions, sign-offs and drafts in files under `.app-state` in the repository root, which git ignores, so a restart shows the same briefs; deleting that folder starts afresh. `docs/user-guide.md` follows every step from starting the application with the seed to a second run that carries earlier decisions.

`APP_SECRET` signs the sign-in cookie (a random one is made for each process when it is absent), `APP_COOKIE` names that cookie, and `APP_TOPICS` lists the topic folders to serve; by default every topic folder with a `review_app/plugin.py` is served. One topic is served by the application's own process; two or more are each served by a process of their own, which the application starts and stops, behind the same address and the same sign-in, because the topic folders keep the starter's package names and those cannot share one process. `APP_STATE_DIR` names the folder that keeps that state (with several topics, each keeps its own in a subfolder named for its topic folder); without it the application keeps everything in memory, as the notebook and the tests do. `APP_SEED=compliance-brief` starts the application with a brief waiting for a reviewer and a brief signed by a fictional reviewer, both runs of the whole document made from the saved calls. The signed brief holds the reviewer's decision on the firm profile and on each fact of the document, her answers to three open questions and her assumption for one, all in her own words and all made through the application's own review routes. Without the seed the application starts empty. A state folder holds one server at a time, and a folder seeded from other recordings, or by a start that stopped partway, is refused with the name of the folder to delete.

## Checks

```bash
make gate
```

takes about ten minutes on the shared machine this was written on, most of it the application's browser tests, and ends with exit code 0. It runs, in order:

1. `ruff check` and `ruff format --check` over every file of the repository.
2. The tests of `fsi_common` and of topic 03. A few tests are skipped by design: the live model call needs `FSI_LIVE_MODEL_TESTS=1`, and the notebook runs belong to `make notebook`. The tests include a scan of every source file and notebook for the LangSmith client methods and HTTP paths that LangSmith removes on 31 January 2027, and a test of the review queue call against a server on the same machine.
3. That the 9 JSON Schemas and the 62 example files are what the code makes, byte for byte.
4. The validator's self-test: 52 valid example records pass, and 45 of 45 planted invalid examples are caught by the check each declares and by no other; 38 of 38 checks have a planted case.
5. The evaluation's planted faults: 6 of 6 caught, each lowering only the measures declared for it.
6. The dataset check: 10 of 10 sections and 48 of 48 paragraphs covered by the labels.
7. The notebook run, whose tests include the check that this README's measure table matches the figures the notebook printed.

If `make gate` fails, the first failing target names the check. Run that target alone, for example `make test` or `make selftest`, to see its full output.

## What is measured

The measures score the list of obligations a section's sub-agent returns for a section of PS26-4 against the reference labels: 39 obligations in 23 of the 48 paragraphs, 16 with a deadline. There are seven, each a count over a stated population; `03_document_summary_agent/evals/README.md` defines each one. No scorer calls a model or imports from the workflow. Every figure below is over all ten sections. The first two columns are printed by the notebook's side-by-side scoring cell, which `make notebook` reruns on the saved calls. The last two are the lines the first whole-document run printed, recorded from 00:02 to 00:06 UTC on 25 November 2026, which `03_document_summary_agent/tests/notebook/test_readme_figures.py` keeps as they were.

| Measure | Starter's agent | This engine | Starter's agent, first run | This engine, first run |
| --- | --- | --- | --- | --- |
| Obligations found, of the labelled obligations in scope | 38 of 39 | 37 of 39 | 36 of 39 | 35 of 39 |
| Invented obligations, of all predicted (lower is better) | 5 of 45 | 5 of 46 | 4 of 42 | 3 of 40 |
| Quotes word for word, of those citing a paragraph in scope | 45 of 45 | 46 of 46 | 42 of 42 | 40 of 40 |
| Deadlines as written, of predicted obligations with a deadline | 25 of 25 | 26 of 26 | 25 of 25 | 21 of 21 |
| Deadlines matched, of matched obligations with a labelled deadline | 16 of 16 | 16 of 16 | 16 of 16 | 15 of 15 |
| Paragraph recall, of paragraphs holding a labelled obligation | 23 of 23 | 23 of 23 | 23 of 23 | 22 of 23 |
| Paragraph precision, of paragraphs holding a predicted obligation | 23 of 28 | 23 of 27 | 23 of 27 | 22 of 25 |

Both agents ran on headless Claude Code through this repository's adapter, and the first two columns come from saved calls and not from the starter's default gateway model. One recorded run is one draw. The starter's agent ran on the same document and the same prompt in both runs and printed different figures, which is why the table sets the two runs beside each other and does not rank the agents. In the replayed run the starter's agent missed 1 of 39 labelled obligations and 5 of the 45 obligations it returned match no label; this engine missed 2 of 39 and 5 of the 46 it returned match no label. In the first run the starter's agent missed 3 of 39 and 4 of its 42 match no label; the engine missed 4 of 39 and 3 of its 40 match no label.

The obligation marker check was added after the first whole-document run missed paragraph 9.3, which says that contracts in place before 1 January 2027 must be updated and was closed as holding no fact. Plain code now looks in every paragraph for the starter's own obligation words ("must", "shall", "is required to", "will need to"). A paragraph that has one and gave no obligation that passed its checks is read a second time on its own, and when that finds nothing it goes to the reviewer as an open question. An obligation read from a paragraph with none of those words goes to the reviewer as one question for that paragraph, resting on every obligation read from it. On the replayed run the engine's first read found paragraph 9.3, so the check sent no paragraph back for a second read, and its forward path is shown by its tests and not by this run.

In the replayed run the engine read 57 facts and all 57 passed their checks, 48 of 48 paragraphs were accounted for, the brief has 50 statements, 4 open questions went to the reviewer, and the marker check sent 0 paragraphs for a second read. Those counts are printed by the notebook and tied to this README by the figures test. What the engine adds is outside the seven measures: every paragraph is accounted for, a person decides before anything is signed, and a reviewer sees each open question. The planted faults and the self-test above test those, and the labels do not score them.

### Repeated runs in LangSmith

`evals/upload.py` puts the two datasets in LangSmith, and `python -m evals.experiments` runs each agent on them as LangSmith experiments, calling the model live, scored by the same seven measures; each run's counts are written to `03_document_summary_agent/evals/data/experiments.json`, and a test ties the table below to that file. The runs below were made on 2026-11-25.

Each column is one experiment. A column for the starter's agent runs its section sub-agent as step 2 of the notebook builds it, one section at a time, with no check after it. A column for this engine runs its section step with the obligation marker check and any second read, and scores the obligations that passed their checks. The table above scores the notebook's own run, where the starter's main agent hands each section to its sub-agent and the engine's first read is scored before any check, so the two tables are read side by side and not cell by cell.

| Measure | Starter's agent, run 1 | Starter's agent, run 2 | Starter's agent, run 3 | Starter's agent, whole document | This engine, run 1 | This engine, run 2 | This engine, run 3 | This engine, whole document |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Obligations found | 36 of 39 | 35 of 39 | 36 of 39 | 35 of 39 | 37 of 39 | 36 of 39 | 36 of 39 | 35 of 39 |
| Invented obligations | 5 of 43 | 6 of 43 | 6 of 44 | 5 of 43 | 7 of 46 | 6 of 45 | 5 of 43 | 6 of 43 |
| Quotes word for word | 43 of 43 | 43 of 43 | 44 of 44 | 43 of 43 | 46 of 46 | 45 of 45 | 43 of 43 | 43 of 43 |
| Deadlines as written | 25 of 25 | 26 of 26 | 25 of 25 | 26 of 26 | 25 of 25 | 25 of 25 | 25 of 25 | 24 of 24 |
| Deadlines matched | 16 of 16 | 16 of 16 | 16 of 16 | 16 of 16 | 16 of 16 | 16 of 16 | 16 of 16 | 16 of 16 |
| Paragraph recall | 23 of 23 | 23 of 23 | 23 of 23 | 23 of 23 | 23 of 23 | 23 of 23 | 23 of 23 | 23 of 23 |
| Paragraph precision | 23 of 28 | 23 of 28 | 23 of 28 | 23 of 28 | 23 of 29 | 23 of 29 | 23 of 27 | 23 of 28 |

The experiments, by column:

- Starter's agent, run 1: `starter-sections-r1-520adde4`, LangSmith experiment `8276a186-5d46-4a79-a093-72ca1530af14`
- Starter's agent, run 2: `starter-sections-r2-76fa8980`, LangSmith experiment `8ec0c5c9-150c-4fff-8843-553a6c449fe8`
- Starter's agent, run 3: `starter-sections-r3-8b2b6167`, LangSmith experiment `482407ea-2257-4b28-9fb2-2af79fecf56b`
- Starter's agent, whole document: `starter-document-r1-659ede03`, LangSmith experiment `ecc48388-482d-4634-ae46-db7f06ffbee5`
- This engine, run 1: `engine-sections-r1-2a8b7eac`, LangSmith experiment `ee54141c-1dbf-48ba-8811-ff55c445814b`
- This engine, run 2: `engine-sections-r2-0af12c04`, LangSmith experiment `05a3e17a-a16f-4384-ba3a-672104962b27`
- This engine, run 3: `engine-sections-r3-016a151e`, LangSmith experiment `6958af25-95ae-4ebb-a073-1f6cee6da615`
- This engine, whole document: `engine-document-r1-dc51c53e`, LangSmith experiment `1b186e7c-507d-4ef9-8b91-dac65f3b588f`

## How the reference labels were made

Two independent labelling agents each read every paragraph of PS26-4, working to written rules fixed before either started. A person did not make the labels. The rules follow the starter's own definition of an obligation: a requirement on the firm marked by "must", "shall", "is required to" or "will need to". The two sets agreed on which 23 paragraphs hold an obligation and differed in 8 of the 48 paragraphs, on how finely to split a paragraph into rows, on one deadline and on whether one obligation applies to the firm. The coordinating session settled each difference under the rules and recorded the reason. The adjudicated file has 77 rows, and its SHA-256 is checked on every build. Both labelling agents are the same model, so their agreement shows how consistently one model reads the rules and says nothing about how a person would read them.

## How it was built

The first build ran from 18:37 to 20:55 UTC on 24 November 2026, 2 hours 17 minutes, in 16 commits; the history since is in `git log`. The record types and the model seam came first and were fixed before anything else was built on them, so that the parts could be built side by side without disagreeing about a record. The repository shows the rest of the method in its tests: a suite for every part, a planted fault for every check, and one command, `make gate`, that runs them all.

By commit time, the parts of the first build landed in this order:

1. 18:37, the workspace layout, the shared records and the model seam.
2. 18:57, the reference dataset, the code evaluators and the planted faults.
3. 19:16, fact identity taken from the source, judged digests and carry-over of earlier decisions; and the chat model over headless Claude Code with record and replay.
4. 19:17 to 19:21, planted faults and the dataset check added to `make gate`, and the checks set to run with tracing off.
5. 20:04 to 20:05, the context layer and the workflow, and the registration of the compliance brief graph.
6. 20:06, the starter's notebook on this repository's model, with the workflow and its scores; at 20:16 the recorded request hash was renamed `request_sha256`, and at 20:21 the notebook's recorded run was added to `make gate`.
7. 20:45, the reviewer's application; at 20:48 its `make serve` target and declared dependencies.
8. 20:49 and 20:55, two fixes to the notebook's text.

How the product works is in plain terms. A context layer reads each source into units, one for each paragraph and one for each table row, and writes a cited fact for each thing a unit says. Plain code checks every quote and every deadline against its paragraph, and a fact that fails stays on the record, marked, and is left out of the brief. The counts close: every unit ends with a fact or on a list of units with no fact and the reason, and a run stops when the counts do not add up. What the sources leave open goes to a named role as an open question. A named person decides on each fact and signs, and an earlier decision on a fact that has not changed is carried to the next run.

## The data and its terms

Every data file in the repository is listed here. All of it is fictional, generated for this build or made from the starter's fictional documents, except the public regulations in the last rows. No customer data, confidential data or personal data is used.

| Path | What it holds | Source and terms |
| --- | --- | --- |
| `03_document_summary_agent/data/documents/PS26-4.md` | Policy Statement PS26/4 on operational resilience: 10 sections, 48 numbered paragraphs | The starter's, byte for byte; fictional |
| `03_document_summary_agent/data/documents.jsonl` | The document library: one row naming PS26-4's file | The starter's, byte for byte |
| `03_document_summary_agent/data/firms.jsonl` | One firm, Harbour Mutual Bank (`FIRM-001`), with its two providers and contract end dates | The starter's, byte for byte; fictional |
| `03_document_summary_agent/data/third_party_providers.jsonl` | NimbusCloud and PayCore Ltd, with the service each provides | The starter's, byte for byte; fictional |
| `03_document_summary_agent/evals/data/reference_labels.tsv` | The 77 adjudicated reference labels over PS26-4 | Made for this build from PS26-4, as described above |
| `03_document_summary_agent/evals/data/sections.jsonl` | One evaluation example for each of the 10 sections | Built by `evals/build_dataset.py` from the labels and PS26-4 |
| `03_document_summary_agent/evals/data/documents.jsonl` | One evaluation example for the whole document and firm | Built by `evals/build_dataset.py` from the labels and PS26-4 |
| `03_document_summary_agent/recordings/` | 26 saved model calls, each holding a request and the answer it received | Made for this build by running the agents on PS26-4 and the firm tables |
| `fsi_common/fsi_common/examples/` | 62 example records, valid and planted invalid | Made for this build by `fsi_common.examples.build`; the reviewer in them is invented |
| `fsi_common/fsi_common/schemas/` | 9 JSON Schemas | Exported from the record types by `fsi_common.export_schemas` |
| `03_document_summary_agent/data/policies/harbour-mutual-bank/manifest.json` | The manifest of Harbour Mutual Bank's policy set: each document's file, the date written, its SHA-256 digest and its terms | Written for this build; fictional |
| `03_document_summary_agent/data/policies/harbour-mutual-bank/policy-governance-framework-v2.0.md` | Harbour Mutual Bank's Policy Governance Framework, version 2.0: the hierarchy of documents, the defined terms, approval and delegation, and the review cycle | Written for this build; fictional |
| `03_document_summary_agent/data/policies/harbour-mutual-bank/ict-risk-management-policy-v3.0.md` | Its ICT Risk Management Policy, version 3.0, in force | Written for this build; fictional |
| `03_document_summary_agent/data/policies/harbour-mutual-bank/ict-risk-management-policy-v2.1.md` | The same policy's version 2.1, superseded by version 3.0 and kept beside it | Written for this build; fictional |
| `03_document_summary_agent/data/policies/harbour-mutual-bank/ict-third-party-risk-standard-v1.3.md` | Its ICT Third-Party Risk Standard, version 1.3 | Written for this build; fictional |
| `03_document_summary_agent/data/policies/harbour-mutual-bank/ict-incident-management-procedure-v1.2.md` | Its ICT Incident Management Procedure, version 1.2 | Written for this build; fictional |
| `03_document_summary_agent/data/policies/harbour-mutual-bank/model-risk-management-policy-v2.0.md` | Its Model Risk Management Policy, version 2.0 | Written for this build; fictional |
| `03_document_summary_agent/data/policies/harbour-mutual-bank/ai-use-standard-v1.0.md` | Its Artificial Intelligence Use Standard, version 1.0 | Written for this build; fictional |
| `03_document_summary_agent/evals/data/policy_seeds.tsv` | 55 seeded cases of the policy set against DORA, the AI Act and SS1/23: for each, the provision with a short quotation of it, the policy clauses that bear on it and the state they leave it in | Written for this build before any engine run read the documents, then compared with a second, blind labelling and settled on written rulings; dated changes are in its header |
| `03_document_summary_agent/evals/data/experiments.json` | The counts of each LangSmith experiment run of the agents on the two datasets | Written by `python -m evals.experiments`; a test ties the experiments table above to it |
| `03_document_summary_agent/data/regulations/texts/dora.xhtml` | Regulation (EU) 2022/2554 (DORA), OJ L 333, 27.12.2022, as the Publications Office serves it, unchanged | © European Union. Fetched from `https://publications.europa.eu/resource/celex/32022R2554` on 25 November 2026, digest `sha256:cf50d8f023d23b2a56f535aaee0760eba7f1925ef08a9858c5c31d43d414f46b`; the notice is quoted below the table |
| `03_document_summary_agent/data/regulations/texts/ai-act.xhtml` | Regulation (EU) 2024/1689 (the AI Act), OJ L, 2024/1689, 12.7.2024, as the Publications Office serves it, unchanged | © European Union. Fetched from `https://publications.europa.eu/resource/celex/32024R1689` on 25 November 2026, digest `sha256:8f0b656302f9864cc87e040c371f209a9d65ae1a6cecc25ca5eb737e872d721a`; the notice is quoted below the table |
| `03_document_summary_agent/data/regulations/sources.json`, `SOURCES.md` | Where each regulation comes from, when it was fetched, its digest and its terms, including the Prudential Regulation Authority's Supervisory Statement SS1/23, whose text is not held here | Made for this build; the statement is fetched from its publisher by `python -m context.regulations fetch` and checked against its digest |
| `03_document_summary_agent/data/regulations/expected/` | For each of the three regulations, the anchor, kind and text digest of every unit it reads into: 501, 930 and 154 units | Made for this build by `python -m context.regulations pin`; holds no regulation text |

The Publications Office's copyright notice, <https://op.europa.eu/en/web/about-us/legal-notices/publications-office-of-the-european-union-copyright>, read on 25 November 2026, says: "The editorial content of this website, which is owned by the EU, is licensed under the Creative Commons Attribution 4.0 International licence. This means that you can reuse it provided you acknowledge the source and indicate any changes you have made." It also says: "Most of the publications on this website are freely available, many of them under Creative Commons licences, and can be downloaded and reproduced provided the source is acknowledged." The first quotation leaves out the link label "(external link)" that the notice page shows between its two sentences; no words are missing. The two texts are split into units for reading and no wording is altered. `test_every_source_paragraph_is_found_word_for_word_in_the_units` checks it: every paragraph of each act, with its footnote references and its own number taken out, is found word for word in the units' text, and `data/regulations/SOURCES.md` has the detail. The address of EUR-Lex's legal notice, <https://eur-lex.europa.eu/content/legal-notice/legal-notice.html>, is taken from the Publications Office's notice and was not opened by the builder; it is where a reader checks the terms.

The Prudential Regulation Authority's Supervisory Statement SS1/23 is not held in the repository. `python -m context.regulations fetch` fetches it from its publisher, which needs a network connection and poppler's `pdftotext`, and `make gate` runs its `regulations-check` target, which uses a copy already cached when its digest matches, before the tests, so a clone without a network connection fails at that step.

## Material from the starter

The starter is [github.com/langchain-samples/fsi-hackathon-london-2026](https://github.com/langchain-samples/fsi-hackathon-london-2026), read at commit `12acee0`. It publishes no licence file. Its material is carried here as the event's published starter for teams to build on, and this README claims nothing more than that about anyone's permission. In topic 03, these files are the starter's, byte for byte:

- `data/documents.jsonl`, `data/documents/PS26-4.md`, `data/firms.jsonl`, `data/third_party_providers.jsonl`
- `instructions.md` and `sub_agent_instructions.md`
- `tools/__init__.py`, `tools/documents.py`, `tools/firms.py`, `tools/third_party_providers.py`
- `utils/__init__.py` and `utils/db.py`

These are the starter's files, adapted:

- `agent.py` passes the model from `get_model("orchestrator")` to `create_deep_agent`.
- `sub_agent.py` runs the sub-agent on `get_model("section")` and returns its `SectionSummary` through a tool call.
- `utils/models.py` is replaced by `get_model(role)` and keeps the starter's exported `model` name.
- `pyproject.toml` keeps the starter's dependencies and adds `fsi-common`.
- `langgraph.json` registers a second graph, `compliance_brief`, beside the starter's.
- `modules/01_document_summary_agent.ipynb` keeps the starter's 23 cells, changed where a model is chosen, and adds 14.

The repository's own work, the contract, adapter, context layer, workflow, evaluations and application, is by Khushil Dep.

## Credits

The FSI hackathon starter and its sample document, firm tables and notebook are from LangChain's [fsi-hackathon-london-2026](https://github.com/langchain-samples/fsi-hackathon-london-2026). The agents are built with LangChain, LangGraph and Deep Agents, and traced with LangSmith.

## Use of the output

Outputs of this product are not legal, compliance or regulatory advice.
