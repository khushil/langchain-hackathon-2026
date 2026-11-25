"""A stand-in for `claude -p` for the notebook tests: it answers the adapter's calls from a script.

No model runs. It plays the starter's assessor (look up the transaction and the profile, record one
assessment from the analysts' scores, reply) and the reasoning judge, through the same command line
the adapter gives the real program, so the notebooks run end to end in record and replay.
"""

import json
import re
import sys
from pathlib import Path

DATA = str(Path(__file__).resolve().parents[2] / "data")
argv = sys.argv[1:]
model = argv[argv.index("--model") + 1]
schema = json.loads(argv[argv.index("--json-schema") + 1]) if "--json-schema" in argv else None
prompt = sys.stdin.read()


def table(name):
    with open(f"{DATA}/{name}.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


scores = {r["transaction_id"]: r["risk_score"] for r in table("analyst_labels")}
scores |= {r["transaction_id"]: r["correct_risk_score"] for r in table("simulated_annotations")}
full = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5"}.get(model, model)
init = {
    "type": "system",
    "subtype": "init",
    "cwd": "/tmp",
    "model": full,
    "tools": ["StructuredOutput"] if schema else [],
    "mcp_servers": [],
    "plugins": [],
    "slash_commands": [],
    "skills": [],
    "agents": [],
    "apiKeySource": "none",
    "claude_code_version": "2.1.302",
}


def done(result="", structured=None):
    event = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": result,
        "num_turns": 1,
        "duration_ms": 1,
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    if structured is not None:
        event["structured_output"] = structured
    print(json.dumps(init))
    print(json.dumps(event))


if schema is None:
    done("Hello from the scripted model.")
    sys.exit(0)

branches = schema["properties"]["tool_calls"]["items"]["anyOf"]
names = [b["properties"]["name"]["const"] for b in branches]
if "Verdict" in names:
    done(
        structured={
            "content": "",
            "tool_calls": [
                {
                    "name": "Verdict",
                    "args": {"sound": True, "explanation": "The reasoning matches the reviewers."},
                }
            ],
        }
    )
    sys.exit(0)

tx = re.findall(r"TX-\d+", prompt)[-1]
start = prompt.rindex("New transaction:")
tail = prompt[start:]
if 'role="tool"' not in tail:
    calls = [
        {"name": "get_transaction", "args": {"transaction_id": tx}},
        {"name": "get_customer_profile", "args": {}},
    ]
    done(structured={"content": "", "tool_calls": calls})
elif 'name="record_decision"' in tail:
    done(structured={"content": f"Looked at {tx}.", "tool_calls": []})
else:
    score = scores.get(tx, 5)
    args = {
        "transaction_id": tx,
        "risk_score": score,
        "confidence": 0.9,
        "decision": "block" if score >= 70 else "approve",
        "reason": f"Scripted reason for score {score}.",
    }
    done(structured={"content": "", "tool_calls": [{"name": "record_decision", "args": args}]})
