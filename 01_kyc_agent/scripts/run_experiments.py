"""Create a LangSmith dataset for the KYC agent and run an offline evaluation against it.

Every customer in `data/applications.jsonl` is a test case. The expected outcome for each one is labelled in evals/data/starter_labels.tsv,
independently of the agent's own matching logic, so the evaluation can expose bugs in that logic (for example the
fuzzy name match flagging a different person, or missing a PEP's relative).

PREREQUISITE: run this script AFTER the agent has been traced at least once (e.g. run the agent, or create its
LangSmith project, with LANGSMITH_PROJECT set). The dataset is linked to the workspace's "Agent" tag value named after
LANGSMITH_PROJECT, and that tag value only exists once the agent has been traced. If it does not exist yet the script
stops with an error before creating or deleting anything.

Run it from `01_kyc_agent` (after `uv sync --all-packages` at the repo root):

    uv run python scripts/run_experiments.py                # create the dataset if needed, then evaluate
    uv run python scripts/run_experiments.py --dataset-only # only create the dataset
    uv run python scripts/run_experiments.py --recreate     # delete and rebuild the dataset first

LANGSMITH_API_KEY and the model gateway settings are read from the shared .env in the repo root.
"""

import argparse
import os
import uuid

import requests
from agent import build_agent
from evals.labels import read_labels
from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from langsmith import Client, evaluate
from utils import PROJECT_ROOT, db

load_dotenv(PROJECT_ROOT.parent / ".env")

# The names below are set by main(), because the starter stopped at import when LANGSMITH_PROJECT was not set, which
# stops anything that only wants the evaluators from importing this file with no key.
DATASET_NAME = ""
AGENT_NAME = ""


def _configure() -> None:
    """Name the dataset and the agent after the attendee's LangSmith project from .env, or stop."""
    global DATASET_NAME, AGENT_NAME
    # Named after the attendee's LangSmith project from .env (fsi-hackathon-<ATTENDEE_NAME>), so datasets don't collide
    if not os.environ.get("LANGSMITH_PROJECT"):
        raise SystemExit("LANGSMITH_PROJECT is not set: copy .env.example to .env in the repo root and fill it in")
    DATASET_NAME = f"{os.environ['LANGSMITH_PROJECT']}-kyc-agent"
    # Links the dataset, the traced graph and the experiments to the agent. The agent (and its "Agent" tag value) is
    # only created in LangSmith once the agent has been run/traced under this name, so trace it before running this.
    AGENT_NAME = os.environ["LANGSMITH_PROJECT"]


#
# Ground truth, labelled per customer by the starter: (risk_level, why)
#
# High risk means the customer genuinely is, or is closely tied to, a sanctioned person or a PEP. The reviewer in the
# evaluation rejects every high-risk case, so the expected decision is "reject" for high and "approve" for low.
#
# The labels are the starter's 25, carried unchanged into evals/data/starter_labels.tsv and read from there.
LABELS: dict[str, tuple[str, str]] = {label.customer_id: (label.risk_level, label.reason) for label in read_labels()}

REVIEWER_ANSWER = {"decision": "reject", "notes": "Offline evaluation: simulated reviewer rejects every high-risk case."}


def expected_decision(risk_level: str) -> str:
    return "reject" if risk_level == "high" else "approve"


#
# Dataset
#
def _build_dataset_examples() -> list[dict]:
    applications = {row["customer_id"]: row for row in db.table("applications")}
    missing = set(LABELS) ^ set(applications)
    if missing:
        raise SystemExit(f"LABELS and data/applications.jsonl disagree on: {sorted(missing)}")

    return [
        {
            "inputs": {"customer_id": customer_id},
            "outputs": {
                "risk_level": risk_level,
                "decision": expected_decision(risk_level),
                "application": applications[customer_id]["application"],
                "label_reason": reason,
            },
            "metadata": {"customer_id": customer_id, "edge_case": reason.startswith("Edge case")},
        }
        for customer_id, (risk_level, reason) in LABELS.items()
    ]


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


#
# Create the dataset
#
def create_dataset(client: Client, recreate: bool):
    # Resolved before any delete so a missing tag can't leave the workspace without the dataset
    agent_tag = _get_agent_tag(client, AGENT_NAME)

    if client.has_dataset(dataset_name=DATASET_NAME):
        if not recreate:
            print(f"Using existing dataset '{DATASET_NAME}' (pass --recreate to rebuild it)")
            return client.read_dataset(dataset_name=DATASET_NAME)
        client.delete_dataset(dataset_name=DATASET_NAME)

    dataset = client.create_dataset(
        DATASET_NAME,
        description="KYC agent offline evaluation: the starter's labelled risk level and decision for every sample application.",
        tag_value_ids=[agent_tag["id"]],
    )
    examples = _build_dataset_examples()
    client.create_examples(dataset_id=dataset.id, examples=examples)
    print(f"Created dataset '{DATASET_NAME}' with {len(examples)} examples")
    return dataset


#
# Target: run the agent end to end
#
def run_agent(inputs: dict) -> dict:
    """Run the full graph for one customer, answering the human_review interrupt with the simulated reviewer."""
    graph = build_agent(name=AGENT_NAME, checkpointer=InMemorySaver())  # interrupt() needs a checkpointer to pause and resume
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    state = graph.invoke({"customer_id": inputs["customer_id"]}, config)
    if "__interrupt__" in state:
        state = graph.invoke(Command(resume=REVIEWER_ANSWER), config)
    return state


#
# Evaluators
#
def risk_level_correct(outputs: dict, reference_outputs: dict) -> dict:
    return {"key": "risk_level_correct", "score": outputs.get("risk_level") == reference_outputs["risk_level"]}


def decision_correct(outputs: dict, reference_outputs: dict) -> dict:
    return {"key": "decision_correct", "score": outputs.get("decision") == reference_outputs["decision"]}


def false_negative(outputs: dict, reference_outputs: dict) -> dict:
    """1 when a genuinely high-risk customer was waved through. The costly failure in KYC, so tracked on its own."""
    missed = reference_outputs["risk_level"] == "high" and outputs.get("risk_level") != "high"
    return {"key": "false_negative", "score": missed}


def false_positive(outputs: dict, reference_outputs: dict) -> dict:
    """1 when a low-risk customer was sent to a human for review. Costs analyst time, not compliance exposure."""
    flagged = reference_outputs["risk_level"] == "low" and outputs.get("risk_level") == "high"
    return {"key": "false_positive", "score": flagged}


def profile_extracted(outputs: dict, reference_outputs: dict) -> dict:
    """The extracted name and date of birth must be consistent with the application text."""
    profile = outputs.get("profile") or {}
    application = reference_outputs["application"]
    name_ok = bool(profile.get("full_name")) and profile["full_name"].lower() in application.lower()
    dob_ok = bool(profile.get("date_of_birth")) and len(profile["date_of_birth"]) == 10  # YYYY-MM-DD
    return {"key": "profile_extracted", "score": name_ok and dob_ok}


def memo_consistent(outputs: dict, reference_outputs: dict) -> dict:
    """The memo must name the customer and state the final decision, and stay under the 120 word limit."""
    memo = (outputs.get("decision_memo") or "").lower()
    name = ((outputs.get("profile") or {}).get("full_name") or "").lower()
    decision_word = {"approve": "approv", "reject": "reject"}[reference_outputs["decision"]]
    ok = bool(name) and name in memo and decision_word in memo and len(memo.split()) <= 150
    return {"key": "memo_consistent", "score": ok}


EVALUATORS = [risk_level_correct, decision_correct, false_negative, false_positive, profile_extracted, memo_consistent]

#
# Main: create the dataset if needed, then run the baseline and again with an updated confidence threshold
#
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset-only", action="store_true", help="create the dataset and stop")
    parser.add_argument("--recreate", action="store_true", help="delete and rebuild the dataset first")
    parser.add_argument("--prefix", default="kyc-agent", help="experiment name prefix")
    parser.add_argument("--concurrency", type=int, default=4, help="parallel agent runs")
    args = parser.parse_args()

    _configure()
    client = Client()
    create_dataset(client, args.recreate)
    if args.dataset_only:
        return

    results = evaluate(
        run_agent,
        data=DATASET_NAME,
        evaluators=EVALUATORS,
        experiment_prefix=args.prefix,
        max_concurrency=args.concurrency,
        client=client,
    )
    print(f"Experiment: {results.experiment_name}")


if __name__ == "__main__":
    main()
