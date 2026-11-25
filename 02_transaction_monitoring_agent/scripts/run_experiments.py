"""Create a LangSmith dataset for the transaction monitoring agent and run an offline evaluation against it.

One dataset example is one customer's whole transaction stream, because the agent's decisions depend on memory.
The target function runs a fresh agent over the stream, and three plain-Python evaluators compare its decisions
with the analysts' labels in `data/analyst_labels.jsonl`.

PREREQUISITE: run this script AFTER the agent has been traced at least once (e.g. run the agent, or create its
LangSmith project, with LANGSMITH_PROJECT set). The dataset is linked to the workspace's "Agent" tag value named after
LANGSMITH_PROJECT, and that tag value only exists once the agent has been traced. If it does not exist yet the script
stops with an error before creating or deleting anything.

Run it from `02_transaction_monitoring_agent` (after `uv sync --all-packages` at the repo root):

    uv run python scripts/run_experiments.py                # create the dataset if needed, then evaluate
    uv run python scripts/run_experiments.py --dataset-only # only create the dataset
    uv run python scripts/run_experiments.py --recreate     # delete and rebuild the dataset first

LANGSMITH_API_KEY and the model gateway settings are read from the shared .env in the repo root.
"""

import argparse
import os

import requests
from agent import build_agent
from dotenv import load_dotenv
from evals.scoring_evals import (
    decision_accuracy_eval,
    review_routing_eval,
    score_alignment_eval,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langsmith import Client, evaluate
from utils import PROJECT_ROOT, db
from utils.attendee import ATTENDEE
from utils.state import OCT_19, MyAgentContext
from utils.transaction_processing import (
    decision_log,
    process_transactions,
    transaction_stream,
)

load_dotenv(PROJECT_ROOT.parent / ".env")

# Named after the attendee's LangSmith project from .env (fsi-hackathon-<ATTENDEE_NAME>), so datasets don't collide.
# Importing this module needs no LangSmith settings, so a notebook can reuse its functions; `main` still insists.
PROJECT = os.environ.get("LANGSMITH_PROJECT") or "compliance-brief"
# The second notebook makes the dataset under this name and the third reads it, so it is named once, here, after
# the attendee and not the project.
DATASET_NAME = f"transaction-monitoring-{ATTENDEE}"

# Links the dataset, the traced graph and the experiments to the agent. The agent (and its "Agent" tag value) is only
# created in LangSmith once the agent has been run/traced under this name, so trace it before running this script.
AGENT_NAME = PROJECT

REVIEWER_ANSWERS = {row["transaction_id"]: row for row in db.table("reviewer_answers")}
EVALUATORS = [decision_accuracy_eval, score_alignment_eval, review_routing_eval]


#
# Dataset
#
def _build_dataset_examples() -> list[dict]:
    """One example per customer: their stream and reviewer answers as inputs, the analysts' labels as outputs."""
    examples = []
    for customer in db.table("customer_profiles"):
        transactions = transaction_stream(customer["user_id"], end=OCT_19)
        ids = [tx["transaction_id"] for tx in transactions]
        examples.append(
            {
                "inputs": {
                    "user_id": customer["user_id"],
                    "transactions": transactions,
                    "reviewer_answers": {tx_id: REVIEWER_ANSWERS[tx_id] for tx_id in ids if tx_id in REVIEWER_ANSWERS},
                },
                "outputs": {"labels": {tx_id: db.get("analyst_labels", transaction_id=tx_id) for tx_id in ids}},
            }
        )
    return examples

def _get_agent_tag(client: Client, agent_name: str) -> dict:
    """Find the workspace's "Agent" tag value matching the agent name, so the dataset can be linked to it by ID.

    The tag value is created by LangSmith when the agent is traced, so it won't exist until the agent has been run.
    """
    response = requests.get(
        f"{client.api_url}/api/v1/workspaces/current/tags", headers={"X-API-Key": client.api_key or ""}, timeout=30
    )
    response.raise_for_status()

    available = []
    for tag in response.json():
        if tag["key"] != "Agent":
            continue
        for tag_value in tag["values"]:
            if tag_value["value"] == agent_name:
                return tag_value
            available.append(tag_value["value"])
    raise SystemExit(
        f"No 'Agent' tag value named '{agent_name}' in this workspace. Run the agent first so it is traced, "
        f"then re-run this script. Available: {sorted(available)}"
    )


def create_dataset(client: Client, recreate: bool):
    """Create the LangSmith dataset and link it to the agent, unless it already exists (`recreate` rebuilds it)."""
    # Resolved before any delete so a missing tag can't leave the workspace without the dataset
    agent_tag = _get_agent_tag(client, AGENT_NAME)

    if client.has_dataset(dataset_name=DATASET_NAME):
        if not recreate:
            print(f"Using existing dataset '{DATASET_NAME}' (pass --recreate to rebuild it)")
            return client.read_dataset(dataset_name=DATASET_NAME)
        client.delete_dataset(dataset_name=DATASET_NAME)

    dataset = client.create_dataset(
        DATASET_NAME,
        description="Transaction monitoring agent: Customer transaction streams with analyst labels.",
        tag_value_ids=[agent_tag["id"]],
    )

    examples = _build_dataset_examples()
    client.create_examples(dataset_id=dataset.id, examples=examples)
    print(f"Created dataset '{DATASET_NAME}' with {len(examples)} examples")
    return dataset

#
# Target: run the agent end to end
#
def run_agent_on_stream(context_settings: MyAgentContext, inputs: dict) -> dict:
    """The target function: run a fresh agent over one customer's stream and return its decisions."""
    agent = build_agent(checkpointer=InMemorySaver(), store=InMemoryStore() )

    process_transactions(
        agent, context_settings=context_settings, transactions=inputs["transactions"], thread_id=inputs["user_id"], reviewer_answers=inputs["reviewer_answers"]
    )

    return {"decisions": decision_log(agent, inputs["user_id"])}


#
# Experiments
#
def average_scores(results) -> dict:
    """Average each evaluator's score across all the examples in an experiment."""
    scores = {}
    for row in results:
        for result in row["evaluation_results"]["results"]:
            scores.setdefault(result.key, []).append(result.score)

    return {key: round(sum(values) / len(values), 2) for key, values in scores.items()}

def run_experiment(prefix: str, context_settings: MyAgentContext) -> dict:
    """Run the evaluation once and return the average scores. The full experiment is saved to LangSmith."""
    
    # `evaluate` calls the target with just the example's inputs, so bind the settings here.
    def target(inputs: dict) -> dict:
        return run_agent_on_stream(context_settings, inputs)

    results = evaluate(target, data=DATASET_NAME, evaluators=EVALUATORS, experiment_prefix=prefix, max_concurrency=2)
    
    return average_scores(results)


#
# Main: create the dataset if needed, then run the baseline and again with an updated confidence threshold
#
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset-only", action="store_true", help="create the dataset and stop")
    parser.add_argument("--recreate", action="store_true", help="delete and rebuild the dataset first")
    args = parser.parse_args()

    if not os.environ.get("LANGSMITH_PROJECT"):
        raise SystemExit("LANGSMITH_PROJECT is not set: copy .env.example to .env in the repo root and fill it in")
    client = Client()
    create_dataset(client, args.recreate)
    if args.dataset_only:
        return

    print("baseline:", run_experiment(prefix="baseline", context_settings=MyAgentContext()))
    print("threshold-0.8:", run_experiment(prefix="threshold-0.8", context_settings=MyAgentContext(confidence_threshold=0.8)))

if __name__ == "__main__":
    main()