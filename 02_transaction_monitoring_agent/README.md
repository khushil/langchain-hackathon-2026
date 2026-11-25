# Transaction monitoring

This topic watches a stream of card transactions for fraud. It starts from the transaction monitoring topic of the FSI hackathon starter: an agent looks each transaction up beside the customer's profile and scores it, remembers the customer's earlier transactions in the conversation and what reviewers have said about the customer in a store, and pauses for a person when it is not confident. Here the agent only proposes. Each proposal is read into a cited fact whose quote is the transaction's own fields, plain code checks it, and a named reviewer decides every transaction in their own words and signs the brief or returns it.

## What is in the folder

| Folder or file | What it holds |
| --- | --- |
| `agent.py`, `tools/`, `instructions.md`, `utils/` | The starter's agent, its three tools and its helpers, with the model chosen through `get_model` |
| `agents.py` | Every agent of the topic by name: the starter's agent and the transaction monitoring graph |
| `context/` | The context layer: a customer's stream read into units, one fact for each thing a unit says, the plain-code checks, the questions and the counts that must close |
| `workflow/` | The transaction monitoring graph: read the stream, assess each transaction, close the counts, write the brief, stop for the reviewer, resume on their response |
| `evals/` | The dataset built from the starter's reference data, the seven measures and the planted faults; `evals/README.md` defines each measure |
| `review_app/` | The topic's plug-in for the reviewer's application: its pages, the picture of the stream, templates and the routes that record a decision |
| `scripts/` | The starter's experiments script |
| `modules/` | The starter's three notebooks with this repository's additions |
| `data/` | The starter's transactions, customers, analyst labels, reviewer replies and simulated reviews |
| `recordings/` | The saved model calls that `replay` answers from |
| `tests/` | The topic's tests |

## Setup

Follow the setup in the [repository README](../README.md): `uv sync --all-packages` in the repository root, then `cp .env.example .env` there. All topics share that one environment and that one `.env`. This topic keeps its saved model calls in its own `recordings/` folder, which is where `get_model` reads from unless `MODEL_RECORDINGS_DIR` names another.

## Run the agent

From this folder, with `MODEL_BACKEND` in `.env` set to `replay` (the default, which answers only from the saved calls), `claude-code` (headless Claude Code on the signed-in account) or `langchain` (the starter's route, with your own provider key and `MODEL_NAME`):

```python
from agent import agent
from utils.state import MyAgentContext

result = agent.invoke(
    {"messages": [{"role": "user", "content": "New transaction: TX-1001"}]},
    context=MyAgentContext(user_id="USR-001"),
)
print(result["messages"][-1].text)
```

Run it with `LANGSMITH_TRACING=false` and `PYTHONPATH=.:../fsi_common` unless you have exported a LangSmith key and installed the workspace with `uv sync --all-packages`.

The transaction monitoring graph runs through `workflow.runs.MonitorRuns`, which the notebook and the reviewer's application both use. It stops at the review step and resumes only from a named person's response.

## How a run goes

A run is one customer's stream, whole or a window of it, which the request gives as `start` and `end`.

1. The stream and the customer's profile are read into units: one for each transaction in the window and one for the profile row. Each field of the profile becomes a fact that quotes the row.
2. The starter's agent assesses the transactions in time order on one conversation thread, so it remembers the earlier ones. Its own pause for a person is switched off; what its `record_decision` tool keeps for a transaction is read as a proposal.
3. Each proposal becomes a fact about its transaction. The quote is the transaction's own fields, copied word for word, and six plain-code checks run on it: the quote is in the transaction's line, every field it names matches the row, the score is a whole number from 0 to 100, the proposed decision follows the starter's rule of blocking from 70, both confidences lie from 0 to 1, and the starter's own checks on the confidence give what was recorded.
4. Every transaction ends with a fact or on a list of units with no fact, with its reason, and the run stops when the counts do not close. A proposal that fails a check stays on the record with the failed check and stays off the brief; the transaction goes to the reviewer as an open question. So does a transaction the agent recorded nothing for.
5. The brief has one statement for each proposal that passed, citing the proposal and the profile fields the starter's checks read. The workflow stops at the review step with the brief, each proposal beside its transaction's line, and what reviewers decided about the customer before.
6. A signed-in person decides each transaction through the reviewer's application: they agree with the proposal, give their own decision (approve or block) or disagree, and write their reason. They answer each open question with approve or block and their reason, and may note an assumption beside the answer, which never settles the question, and then sign the brief or return it. A brief with a disagreement can only be returned.

The reviewer's decisions are kept in the store under the customer. A later run on the same customer shows them beside the new proposals, carries a decision whose judged content is unchanged, and asks again, naming what changed, when it is not.

## Models by role

`utils/models.py` is the one place a model is chosen. `get_model(role)` returns the model for each role:

| Role | Model | Effort | Used for |
| --- | --- | --- | --- |
| `assessor` | `claude-sonnet-5-5` | medium | The starter's agent, which looks each transaction up and records a proposal that plain code then checks |
| `judge` | `claude-opus-5-5` | medium | The starter's reasoning judge of the third notebook |

`get_model` stops with `TracingKeyMissingError` when `LANGSMITH_TRACING` is `true` and the LangSmith key is empty, so no run loses its traces without saying so.

## Files that differ from the starter

| File | Difference |
| --- | --- |
| `agent.py` | Passes `get_model("assessor")` to `create_agent` in place of `init_chat_model(model)`, and takes an optional `model` so a caller can pass its own |
| `utils/models.py` | `get_model(role)`; the starter's `model` name is still exported |
| `scripts/run_experiments.py` | Importing it no longer stops when `LANGSMITH_PROJECT` is unset, because the third notebook imports from it, and the dataset is named `transaction-monitoring-<attendee>`, the name the second notebook makes it under, where the starter's script named it after the project; running it still insists on the project |
| `langgraph.json` | Registers `transaction_monitoring`, the graph in `workflow/graph.py`, beside the starter's agent |
| `pyproject.toml` | The starter's dependencies except `managed-deepagents`, with `fsi-common`, `pydantic` and `langgraph-checkpoint-sqlite` added |
| `modules/01_transaction_monitoring_agent.ipynb` | The starter's 42 cells, changed where a model is chosen and where the agent's graph is drawn, followed by cells that add the facts, the accounting, the review and the scoring |
| `modules/02_scoring_evals.ipynb` | The starter's 15 cells, changed where a model is chosen, with each step that needs LangSmith printing one sentence and doing nothing without a key, followed by cells that score the same runs without LangSmith |
| `modules/03_annotation_queue.ipynb` | The starter's 20 cells, changed in the same two ways and with the judge on the `judge` role, with the cell that puts the runs in the review queue reading each run's project and start time from LangSmith and adding the runs through the queue's items, because LangSmith removes the add-by-run-id call on 31 January 2027, followed by cells that read the four simulated reviews from the data and run the judge and the evaluation locally |
| `agents.py`, `context/`, `workflow/`, `evals/`, `review_app/`, `recordings/`, `tests/` | Added |
| `utils/records.py`, `utils/review.py`, `utils/langsmith_key.py` | Added: the topic's fact kinds, the review's payload and resume value with the store namespaces, and the check that a notebook step may write to LangSmith |

The instructions, the three tools, the starter's other helpers, the evaluators of `evals/scoring_evals.py`, the images and the data are the starter's, byte for byte; a test fails if one of them changes.

One carried file speaks in the agent's name. The starter's decision tool tells the model that a decision was made "by agent" and stores `decided_by: "agent"` with what the agent records. This build reads that record as a proposal and ignores the field. The decision that counts is the one the review records from the signed-in person, and the traces of the model's calls show the starter's wording.

## The data

| File | What it holds | Source and terms |
| --- | --- | --- |
| `data/transactions.jsonl` | Fifteen card transactions of two customers | Fictional, from the starter |
| `data/customer_profiles.jsonl` | Priya Shah in London and Tomás Ferreira in Lisbon, with their usual spend | Fictional, from the starter |
| `data/analyst_labels.jsonl` | The analysts' decision, score and whether a person was warranted for eleven transactions | From the starter |
| `data/reviewer_answers.jsonl` | The two replies the starter's scripted reviewer gives when asked | From the starter |
| `data/simulated_annotations.jsonl` | The four reviews the starter's third notebook simulates for the week after | From the starter |
| `evals/data/examples.jsonl` | Three evaluation examples built from those files | Made for this build, from the starter's files |
| `recordings/` | The saved model calls | Made for this build |

The starter is [github.com/langchain-samples/fsi-hackathon-london-2026](https://github.com/langchain-samples/fsi-hackathon-london-2026), read at commit `12acee0`. It publishes no licence file; its material is carried here as the event's published starter for teams to build on.

## The saved run

`recordings/` holds 94 saved model calls, 78 on Sonnet that assess transactions and 16 on Opus that judge the starter's reasoning, made by running the three notebooks on the starter's data, into one folder. With `MODEL_BACKEND` at `replay` they answer every model call of the notebooks, the application's seed and the offline file, so none of them needs a key; a request with no saved call stops with the request's hash, and the run is never answered from a guess. The notebooks carry the outputs of a replay with no LangSmith key, so each step that writes to LangSmith prints one sentence saying so, and `make notebook` fails if a notebook's outputs are not what a new replay gives.

`APP_SEED=transaction-monitoring make serve` starts the reviewer's application with two reviews of the first customer: one waiting for a reviewer and one signed by a fictional reviewer through the review routes. `PYTHONPATH=fsi_common:03_document_summary_agent python -m fsi_common.app.offline --topic transaction-monitoring --out build/transaction-monitoring-offline.html`, run from the repository root, writes the topic's pages for that run into one HTML file that opens with no server. `docs/user-guide.md` follows every step.

## Tests and checks

From the repository root, `make test` runs one pytest line for each member, this topic's after the shared member's and topic 03's. They make no model call: the model is replaced by a scripted stand-in, and tracing is off. `make planted-faults` and `make dataset-check` run the evaluation's checks, `make notebook` runs the notebooks, and `make serve` starts the reviewer's application, which serves every built topic, this one at `/transaction-monitoring/`. `make gate` runs them all.
