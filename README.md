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
| `replay` (the default) | Calls are answered from the 17 saved calls in `03_document_summary_agent/recordings/`. A request with no recording fails by name; replay never invents an answer. |
| `claude-code` | Each call runs headless Claude Code on your signed-in account, with no tools and no access to your connectors, files or settings. The adapter reads every call's start event and refuses the answer if anything else was loaded. No provider key is needed. |
| `record` | As `claude-code`, and each call is also saved to the recordings folder. |
| `langchain` | The starter's route: `init_chat_model(MODEL_NAME)` with a provider key of your own, as `provider:model`. |

`03_document_summary_agent/utils/models.py` is the one place a model is chosen, by the role of the call: the main agent and the brief writer on Opus, each section's sub-agent on Sonnet. The saved calls cover the starter's agent on the whole of PS26-4 and this repository's workflow on section 7, which are the two runs the notebook and the application make. Any other request needs `claude-code`.

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

`03_document_summary_agent/modules/01_document_summary_agent.ipynb` has 37 cells. The first 23 are the starter's notebook, changed only where a model is chosen, which now goes through `get_model`. The 14 after them add four things: the starter's section summaries scored against the reference labels, the same document read into cited facts, the same scoring of this repository's section 7 beside the starter's, and the place where a person signs. The notebook keeps its outputs from a run on the saved calls.

```bash
make notebook
```

runs it top to bottom on the saved calls with no key and no live call, and ends with `10 passed`. `make gate` includes it.

## The reviewer's application

```bash
make serve
```

starts the application on `APP_HOST` and `APP_PORT`, which default to `0.0.0.0` and `4803`, so it listens on every interface of the machine. To keep it to your own machine, start it as `APP_HOST=127.0.0.1 APP_PORT=4821 make serve`, which prints `Uvicorn running on http://127.0.0.1:4821 (Press CTRL+C to quit)`, and open that address. Add `PYTHON=/path/to/python` when you did not use `uv sync`.

With `MODEL_BACKEND` at its default of `replay`, the application can only start a brief that has saved calls, which is section 7 of PS26-4 for Harbour Mutual Bank; a brief on another section stops with the reason "Replay has no recording for request" followed by the request's hash. With `MODEL_BACKEND=claude-code` in `.env`, any section or the whole document can be started and each brief's model calls run on headless Claude Code.

The application is called Review desk. Its pages are the home page, About, sign-in, and for the compliance brief topic the list of briefs with the form that starts one, the review page, the facts table and the page of a signed or returned brief. About says what the data is. `make serve` keeps the runs, decisions, sign-offs and drafts in files under `.app-state` in the repository root, which git ignores, so a restart shows the same briefs; deleting that folder starts afresh. `docs/user-guide.md` follows every step from signing in to a second run that carries earlier decisions.

`APP_SECRET` signs the sign-in cookie (a random one is made for each process when it is absent), `APP_COOKIE` names that cookie, and `APP_TOPICS` lists the topic folders to serve; by default every topic folder with a `review_app/plugin.py` is served. `APP_STATE_DIR` names the folder that keeps that state; without it the application keeps everything in memory, as the notebook and the tests do. `APP_SEED=compliance-brief` starts the application with a brief waiting for a reviewer and a brief signed by a fictional reviewer, both made from the saved calls; without it the application starts empty. A state folder holds one server at a time, and a folder seeded from other recordings, or by a start that stopped partway, is refused with the name of the folder to delete.

## Checks

```bash
make gate
```

takes about a minute on the machine this was written on and ends with exit code 0. It runs, in order:

1. `ruff check` and `ruff format --check` over 198 files.
2. The tests of `fsi_common` (384 passed, 1 skipped, a live model call that needs `FSI_LIVE_MODEL_TESTS=1`) and of topic 03 (755 passed, 3 skipped, the notebook runs that `make notebook` does).
3. That the 9 JSON Schemas and the 62 example files are what the code makes, byte for byte.
4. The validator's self-test: 52 valid example records pass, and 45 of 45 planted invalid examples are caught by the check each declares and by no other; 38 of 38 checks have a planted case.
5. The evaluation's planted faults: 6 of 6 caught, each lowering only the measures declared for it.
6. The dataset check: 10 of 10 sections and 48 of 48 paragraphs covered by the labels.
7. The notebook run: 17 tests passed, which include the check that this README's measure table matches the figures the notebook printed.

If `make gate` fails, the first failing target names the check. Run that target alone, for example `make test` or `make selftest`, to see its full output.

## What is measured

The measures score the list of obligations a section's sub-agent returns for a section of PS26-4 against the reference labels: 39 obligations in 23 of the 48 paragraphs, 16 with a deadline. There are seven, each a count over a stated population; `03_document_summary_agent/evals/README.md` defines each one. No scorer calls a model or imports from the workflow. The figures below are printed by the notebook's scoring cells, and `make notebook` reruns them.

| Measure | Starter's agent, all 10 sections | Starter's agent, section 7 | This engine, section 7 |
| --- | --- | --- | --- |
| Obligations found, of the labelled obligations in scope | 35 of 39 | 4 of 4 | 4 of 4 |
| Invented obligations, of all predicted (lower is better) | 7 of 45 | 1 of 6 | 1 of 6 |
| Quotes word for word, of those citing a paragraph in scope | 45 of 45 | 6 of 6 | 6 of 6 |
| Deadlines as written, of predicted obligations with a deadline | 28 of 28 | 5 of 5 | 4 of 4 |
| Deadlines matched, of matched obligations with a labelled deadline | 15 of 15 | 3 of 3 | 3 of 3 |
| Paragraph recall, of paragraphs holding a labelled obligation | 23 of 23 | 3 of 3 | 3 of 3 |
| Paragraph precision, of paragraphs holding a predicted obligation | 23 of 29 | 3 of 4 | 3 of 4 |

Both agents ran on headless Claude Code through this repository's adapter, from saved calls, and not on the starter's default gateway model. Over the whole document the starter's agent missed 4 of 39 labelled obligations (one in section 5, one in section 6 and two in section 8), and 7 of the 45 obligations it returned match no label. This engine was run on section 7 only, because the saved run covers that one section, so it has no whole-document figures. On section 7 the two score alike on all seven measures; the one count that differs is deadlines as written, 5 of 5 for the starter's agent and 4 of 4 for this engine, each complete. There is no measure on which this engine scores below the starter's agent, and none on which it scores above: its sub-agent returns the same shape and finds the same obligations. What the engine adds is outside these seven measures: every one of its 18 facts in the section 7 run passed its quote and deadline checks, every paragraph is accounted for, and a person decides before anything is signed. Those are tested by the planted faults and the self-test above, and not scored against the labels.

`evals/upload.py` puts the two datasets in LangSmith. This repository reports no LangSmith experiment results.

## How the reference labels were made

Two independent labelling agents each read every paragraph of PS26-4, working to written rules fixed before either started. A person did not make the labels. The rules follow the starter's own definition of an obligation: a requirement on the firm marked by "must", "shall", "is required to" or "will need to". The two sets agreed on which 23 paragraphs hold an obligation and differed in 8 of the 48 paragraphs, on how finely to split a paragraph into rows, on one deadline and on whether one obligation applies to the firm. The coordinating session settled each difference under the rules and recorded the reason. The adjudicated file has 77 rows, and its SHA-256 is checked on every build. Both labelling agents are the same model, so their agreement shows how consistently one model reads the rules and says nothing about how a person would read them.

## How it was built

The first commit is dated 18:37 UTC on 24 November 2026 and the last commit before this README is dated 20:55 UTC the same day, 2 hours 17 minutes later; there are 16 commits between them and including both. The record types and the model seam came first and were fixed before anything else was built on them, so that the parts could be built side by side without disagreeing about a record. The repository shows the rest of the method in its tests: a suite for every part, a planted fault for every check, and one command, `make gate`, that runs them all.

By commit time, the parts landed in this order:

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

Every data file in the repository is listed here. All of it is fictional, generated for this build or made from the starter's fictional documents. No customer data, confidential data or personal data is used.

| Path | What it holds | Source and terms |
| --- | --- | --- |
| `03_document_summary_agent/data/documents/PS26-4.md` | Policy Statement PS26/4 on operational resilience: 10 sections, 48 numbered paragraphs | The starter's, byte for byte; fictional |
| `03_document_summary_agent/data/documents.jsonl` | The document library: one row naming PS26-4's file | The starter's, byte for byte |
| `03_document_summary_agent/data/firms.jsonl` | One firm, Harbour Mutual Bank (`FIRM-001`), with its two providers and contract end dates | The starter's, byte for byte; fictional |
| `03_document_summary_agent/data/third_party_providers.jsonl` | NimbusCloud and PayCore Ltd, with the service each provides | The starter's, byte for byte; fictional |
| `03_document_summary_agent/evals/data/reference_labels.tsv` | The 77 adjudicated reference labels over PS26-4 | Made for this build from PS26-4, as described above |
| `03_document_summary_agent/evals/data/sections.jsonl` | One evaluation example for each of the 10 sections | Built by `evals/build_dataset.py` from the labels and PS26-4 |
| `03_document_summary_agent/evals/data/documents.jsonl` | One evaluation example for the whole document and firm | Built by `evals/build_dataset.py` from the labels and PS26-4 |
| `03_document_summary_agent/recordings/` | 17 saved model calls, each holding a request and the answer it received | Made for this build by running the agents on PS26-4 and the firm tables |
| `fsi_common/fsi_common/examples/` | 62 example records, valid and planted invalid | Made for this build by `fsi_common.examples.build`; the reviewer in them is invented |
| `fsi_common/fsi_common/schemas/` | 9 JSON Schemas | Exported from the record types by `fsi_common.export_schemas` |

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
