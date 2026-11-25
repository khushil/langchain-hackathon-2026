# KYC onboarding

This topic checks a new customer's application before the bank takes their money. It starts from the KYC onboarding topic of the FSI hackathon starter: a LangGraph graph reads an application, screens the name against a sanctions list and a list of politically exposed people, scores the risk, sends a high-risk customer to a person and writes a decision memo. Here each of the 25 applications is also read into cited facts in the records of `fsi_common`, set against every entry of both lists, and put to a named reviewer, who decides and signs. The repository README gives the figures and says how they were made.

## What is in the folder

| Folder or file | What it holds |
| --- | --- |
| `agent.py`, `tools/`, `utils/state.py`, `utils/db.py`, `utils/nodes.py` | The starter's graph, its lookups and its state, with the model chosen through `get_model` |
| `agents.py` | Every agent of the topic by name: the starter's graph and the onboarding workflow |
| `context/` | The context layer: applications and lists read into units, each detail as a fact with a quote, the screening of every application against every entry, the proposal for each application, and the counts that must close |
| `workflow/` | The onboarding graph: read the applications, screen them, close the counts, write the statements, stop for the reviewer, resume on their response |
| `evals/` | The starter's labels, the dataset, the measures and the planted faults; `evals/README.md` defines each measure |
| `review_app/` | The topic's plug-in for the reviewer's application: its pages, templates, seed and offline edition |
| `scripts/run_experiments.py` | The starter's experiment script, reading its labels from the data file |
| `recordings/` | The 78 saved model calls that `replay` answers from |
| `modules/` | The starter's notebook with this repository's additions |
| `data/` | The starter's applications and its two lists |
| `tests/` | The topic's tests |

## Setup

Follow the setup in the [repository README](../README.md): `uv sync --all-packages` in the repository root, then `cp .env.example .env` there. All topics share that one environment and that one `.env`.

## Run it

`make notebook` in the repository root runs `modules/01_kyc_agent.ipynb` top to bottom on the saved calls, with no key and no live call. To run the onboarding workflow itself, from this folder with `MODEL_BACKEND` at its default of `replay`:

```python
import time

from workflow.requests import request_text
from workflow.runs import KycRuns

runs = KycRuns()
thread = runs.start({"request": request_text()})
while runs.status(thread) == "running":
    time.sleep(0.2)
print(runs.status(thread))
```

It prints `awaiting_review`: the run reads all 25 applications, screens 350 pairings and stops, because only a signed-in person in the reviewer's application can decide. Run it with `LANGSMITH_TRACING=false PYTHONPATH=.:../fsi_common` unless you have exported a LangSmith key and installed the workspace with `uv sync --all-packages`.

The saved calls are those of the notebook's run, so they answer the notebook and the workflow. The starter's own `agent.py` asks the model in slightly different words from the notebook's copy of its nodes, so it needs `MODEL_BACKEND=claude-code` to run outside the notebook.

## Models by role

`utils/models.py` is the one place a model is chosen. `get_model(role)` returns the model for each role:

| Role | Model | Effort | Used for |
| --- | --- | --- | --- |
| `extract` | `claude-sonnet-5-5` | medium | Reading one application into the applicant's details, each with a quote that plain code checks |
| `memo` | `claude-opus-5-5` | medium | The starter's decision memo for the audit file |

The workflow writes no text for the reviewer with a model: each statement is made by code from the proposal's own words, and the memo belongs to the starter's graph. `get_model` stops with `TracingKeyMissingError` when `LANGSMITH_TRACING` is `true` and the LangSmith key is empty.

## Files that differ from the starter

| File | Difference |
| --- | --- |
| `utils/nodes.py` | Asks for its models through `get_model("extract")` and `get_model("memo")` in place of `init_chat_model`; nothing else changes |
| `utils/models.py` | `get_model(role)`; the starter's `model` name is still exported |
| `langgraph.json` | Registers `kyc_onboarding`, the graph in `workflow/graph.py`, beside the starter's |
| `pyproject.toml` | The starter's dependencies, with `fsi-common`, `pydantic` and `langgraph-checkpoint-sqlite` added |
| `scripts/run_experiments.py` | Reads its labels from `evals/data/starter_labels.tsv`; its evaluators, dataset builder and target are the starter's |
| `modules/01_kyc_agent.ipynb` | The starter's 35 cells, changed where a model is chosen and where a sentence was stale, followed by 16 cells that run the workflow and score it |
| `agents.py`, `context/`, `workflow/`, `evals/`, `review_app/`, `recordings/`, `tests/` | Added |
| `utils/records.py`, `utils/kyc_state.py` | Added: the topic's fact kinds, and the graph's state, the review interrupt's payload and the store namespaces for earlier decisions |

The agent, the tools, `utils/state.py`, `utils/db.py` and the data are the starter's, byte for byte.

## The data

| File | What it holds | Source and terms |
| --- | --- | --- |
| `data/applications.jsonl` | 25 account applications, one customer each | Fictional, from the starter |
| `data/sanctions_list.jsonl` | 8 sanctions entries | Fictional, from the starter |
| `data/pep_list.jsonl` | 6 entries of politically exposed people | Fictional, from the starter |
| `evals/data/` | The starter's labels, and the evaluation examples built from them | The labels are the starter's; the examples are built by `evals/build_dataset.py` |
| `recordings/` | 78 saved model calls | Made for this build |

The starter is [github.com/langchain-samples/fsi-hackathon-london-2026](https://github.com/langchain-samples/fsi-hackathon-london-2026), read at commit `12acee0`. It publishes no licence file; its material is carried here as the event's published starter for teams to build on.
