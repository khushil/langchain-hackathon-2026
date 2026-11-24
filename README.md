# Compliance brief workflow

This repository builds the compliance brief topic of the FSI hackathon starter: a regulatory document is read
into facts, each citing a paragraph with a word-for-word quote, and those facts become a brief for one firm that
a named person reviews and signs. It is laid out as the starter is, with one folder per topic in a single uv
workspace and a shared member, `fsi_common`, that holds the record types every topic would use.

Outputs of this product are not legal, compliance or regulatory advice.

## Layout

| Folder | What it holds | State |
| --- | --- | --- |
| `fsi_common/` | The shared record types (sources, source units, facts, open questions, disagreements, decisions, briefs, sign-offs, unit accounting), their JSON Schemas, valid and invalid examples, and a validator | Built |
| `03_document_summary_agent/` | The compliance brief topic: the starter's deep agent, its sub-agent and tools, the model chosen by role, and the graph's state types | Built |
| `01_kyc_agent/` | The starter's KYC onboarding topic | A README only |
| `02_transaction_monitoring_agent/` | The starter's transaction monitoring topic | A README only |

## Setup

You need Python 3.11 or later and [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync --all-packages
cp .env.example .env
```

`.env` holds references to your shell environment and no key. `MODEL_BACKEND` in `.env` chooses where model
calls go; the default, `replay`, answers only from saved recordings, so nothing calls a model until you change
it. The comments in `.env.example` describe each setting.

## Checks

```bash
make gate
```

This runs the linter, the test suite, the checks that the JSON Schemas and the example files match the code that
makes them, and the validator's self-test, which must catch every planted invalid example for the reason it
declares. If `make gate` fails, the
first failing target names the check; run that target alone (`make test`, `make selftest`) to see its full output.

## Credits

The sample data (the fictional policy statement PS26-4, the firm and the third-party providers) and the shape of
each topic come from the FSI hackathon starter,
[github.com/langchain-samples/fsi-hackathon-london-2026](https://github.com/langchain-samples/fsi-hackathon-london-2026).
