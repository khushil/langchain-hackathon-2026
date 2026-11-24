# Compliance brief

This topic turns a regulatory document into a brief for one firm. It starts from the compliance brief topic of the FSI hackathon starter: a deep agent hands each section of the fictional policy statement PS26-4 to a `section-summariser` sub-agent, which returns a `SectionSummary` of `Obligation` rows (requirement, paragraph, deadline as written, and a quote of at most 30 words), and the main agent combines them into a brief. Here the document is also read into cited facts in the records of `fsi_common`, plain code checks each quote and deadline against its paragraph, and a named reviewer decides on each fact and signs the brief or returns it.

## What is in the folder

| Folder or file | What it holds |
| --- | --- |
| `agent.py`, `sub_agent.py`, `tools/`, `instructions.md`, `sub_agent_instructions.md` | The starter's deep agent, its sub-agent and tools, with the model chosen through `get_model` |
| `agents.py` | Every agent of the topic by name: the starter's agent, the section sub-agent and the compliance brief graph |
| `context/` | The context layer: a document or table read into units, one fact for each thing a unit says, the plain-code checks, and the counts that must close |
| `workflow/` | The compliance brief graph: read the sources, fan out the sections, close the counts, write the brief, stop for the reviewer, resume on their response |
| `evals/` | The reference labels, the dataset, the seven measures and the planted faults; `evals/README.md` defines each measure |
| `review_app/` | The topic's plug-in for the reviewer's application: its pages, templates and the routes that record a decision |
| `recordings/` | The 17 saved model calls that `replay` answers from |
| `modules/` | The starter's notebook with this repository's additions |
| `data/` | The starter's document, firm and provider tables |
| `tests/` | The topic's tests |

## Setup

Follow the setup in the [repository README](../README.md): `uv sync --all-packages` in the repository root, then `cp .env.example .env` there. All topics share that one environment and that one `.env`.

## Run the agent

From this folder, with `MODEL_BACKEND` in `.env` set to `replay` (the default, which answers only from the saved calls), `claude-code` (headless Claude Code on the signed-in account) or `langchain` (the starter's route, with your own provider key and `MODEL_NAME`):

```python
from agent import agent

result = agent.invoke(
    {"messages": [{"role": "user", "content": "Summarise document PS26-4 for FIRM-001"}]}
)
print(result["messages"][-1].text)
```

On the saved calls this prints a brief that begins `# PS26/4 brief for Harbour Mutual Bank (FIRM-001)`. Run it with `LANGSMITH_TRACING=false` and `PYTHONPATH=.:../fsi_common` unless you have exported a LangSmith key and installed the workspace with `uv sync --all-packages`.

The compliance brief graph runs through `workflow.runs.BriefRuns`, which the notebook and the reviewer's application both use. It stops at the review step and resumes only from a named person's response.

## Models by role

`utils/models.py` is the one place a model is chosen. `get_model(role)` returns the model for each role:

| Role | Model | Effort | Used for |
| --- | --- | --- | --- |
| `orchestrator` | `claude-opus-5-5` | medium | The main deep agent, which routes the sections and writes the brief from their summaries |
| `section` | `claude-sonnet-5-5` | medium | Each section's sub-agent, whose quotes plain code checks |
| `reconcile` | `claude-opus-5-5` | high | Comparing facts across sections and against the firm's profile |
| `brief` | `claude-opus-5-5` | high | Writing the statements the reviewer signs |

`get_model` stops with `TracingKeyMissingError` when `LANGSMITH_TRACING` is `true` and the LangSmith key is empty, so no run loses its traces without saying so.

## Files that differ from the starter

| File | Difference |
| --- | --- |
| `agent.py` | Passes `get_model("orchestrator")` to `create_deep_agent` in place of `init_chat_model(model)` |
| `sub_agent.py` | The sub-agent runs on `get_model("section")` and returns its `SectionSummary` through a tool call; `Obligation` and `SectionSummary` are as the starter has them |
| `utils/models.py` | `get_model(role)`; the starter's `model` name is still exported |
| `langgraph.json` | Registers `compliance_brief`, the graph in `workflow/graph.py`, beside the starter's agent |
| `pyproject.toml` | The starter's dependencies, with `fsi-common` added as a workspace dependency |
| `modules/01_document_summary_agent.ipynb` | The starter's 23 cells, changed where a model is chosen, followed by 14 cells that score the starter's agent and this repository's engine and show the review step |
| `agents.py`, `context/`, `workflow/`, `evals/`, `review_app/`, `recordings/`, `tests/` | Added |
| `utils/records.py`, `utils/state.py` | Added: the topic's fact kinds and the conversions between `Obligation` and cited facts; the graph's state, the review interrupt's payload and resume value, and the store namespaces for earlier decisions |

The instructions, the tools, `utils/db.py` and the data are the starter's, byte for byte.

## The data

| File | What it holds | Source and terms |
| --- | --- | --- |
| `data/documents/PS26-4.md` | Policy Statement PS26/4 on operational resilience: 10 sections, 48 numbered paragraphs | Fictional, from the starter |
| `data/documents.jsonl` | The document library: one row naming PS26-4's file | From the starter |
| `data/firms.jsonl` | One firm, Harbour Mutual Bank (`FIRM-001`), with its two providers and contract end dates | Fictional, from the starter |
| `data/third_party_providers.jsonl` | NimbusCloud and PayCore Ltd, with the service each provides | Fictional, from the starter |
| `evals/data/` | The reference labels, and the evaluation examples built from them | Made for this build; see the repository README |
| `recordings/` | 17 saved model calls | Made for this build |

The starter is [github.com/langchain-samples/fsi-hackathon-london-2026](https://github.com/langchain-samples/fsi-hackathon-london-2026), read at commit `12acee0`. It publishes no licence file; its material is carried here as the event's published starter for teams to build on.

## Tests and checks

From the repository root, `make test` runs this topic's tests with the shared member's. They make no model call: the model adapter is replaced by a fake, and tracing is off. `make planted-faults` and `make dataset-check` run the evaluation's checks, `make notebook` runs the notebook on the saved calls, and `make serve` starts the reviewer's application. `make gate` runs them all.
