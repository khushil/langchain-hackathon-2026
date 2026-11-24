# Compliance brief

This topic turns a regulatory document into a brief for one firm. It starts from the compliance brief topic of
the FSI hackathon starter: a deep agent hands each section of the fictional policy statement PS26-4 to a
`section-summariser` sub-agent, which returns a `SectionSummary` of `Obligation` rows (requirement, paragraph,
deadline as written, and a quote of at most 30 words), and the main agent combines them into a brief. Here every
obligation also becomes a cited fact in the records of `fsi_common`, so later steps can check each quote against
its paragraph and a named reviewer can decide on each one.

## Setup

Follow the setup in the [repository README](../README.md): `uv sync --all-packages` in the repository root,
then `cp .env.example .env` there. All topics share that one environment and that one `.env`.

## Run the agent

From this folder, with `MODEL_BACKEND` in `.env` set to `claude-code` (headless Claude Code on the signed-in
account) or `langchain` (the starter's route, with your own provider key and `MODEL_NAME`):

```python
from agent import agent

result = agent.invoke(
    {"messages": [{"role": "user", "content": "Summarise document PS26-4 for FIRM-001"}]}
)
print(result["messages"][-1].text)
```

With the default, `replay`, the agent answers only from saved recordings and makes no model call.
To chat with the agent in LangGraph Studio, run `uv run langgraph dev` from this folder.

## Models by role

`utils/models.py` is the one place a model is chosen. `get_model(role)` returns the model for each role:

| Role | Model | Effort | Used for |
| --- | --- | --- | --- |
| `orchestrator` | `claude-opus-5-5` | medium | The main deep agent, which routes the sections and writes the brief from their summaries |
| `section` | `claude-sonnet-5-5` | medium | Each section's sub-agent, whose quotes plain code checks |
| `reconcile` | `claude-opus-5-5` | high | Comparing facts across sections and against the firm's profile |
| `brief` | `claude-opus-5-5` | high | Writing the statements the reviewer signs |

`get_model` stops with `TracingKeyMissingError` when `LANGSMITH_TRACING` is `true` and the LangSmith key is
empty, so no run loses its traces without saying so.

## Files that differ from the starter

| File | Difference |
| --- | --- |
| `agent.py` | Passes `get_model("orchestrator")` to `create_deep_agent` in place of `init_chat_model(model)` |
| `sub_agent.py` | The sub-agent runs on `get_model("section")` and returns its `SectionSummary` through a tool call; `Obligation` and `SectionSummary` are as the starter has them |
| `utils/models.py` | `get_model(role)`; the starter's `model` name is still exported |
| `agents.py` | Added: every agent of the topic by name |
| `utils/records.py` | Added: the topic's fact kinds, and conversions from `Obligation` and `SectionSummary` to cited facts and back |
| `utils/state.py` | Added: the graph's state, the review interrupt's payload and resume value, and the store namespaces for earlier decisions |

The instructions, the tools, `utils/db.py`, `langgraph.json` and the data are the starter's, byte for byte.

## The data

| File | What it holds | Source and terms |
| --- | --- | --- |
| `data/documents/PS26-4.md` | Policy Statement PS26/4 on operational resilience: 10 sections, 48 numbered paragraphs | Fictional, from the starter |
| `data/documents.jsonl` | The document library: one row naming PS26-4's file | From the starter |
| `data/firms.jsonl` | One firm, Harbour Mutual Bank (`FIRM-001`), with its two providers and contract end dates | Fictional, from the starter |
| `data/third_party_providers.jsonl` | NimbusCloud and PayCore Ltd, with the service each provides | Fictional, from the starter |

The starter is [github.com/langchain-samples/fsi-hackathon-london-2026](https://github.com/langchain-samples/fsi-hackathon-london-2026).

## Tests

From the repository root, `make test` runs this topic's tests with the shared member's. They make no model
call: the model adapter is replaced by a fake, and tracing is off.
