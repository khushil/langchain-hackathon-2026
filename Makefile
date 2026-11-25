# Checks for the repository. Every target runs only commands inside this folder.
# After `uv sync --all-packages` the defaults below use .venv; another interpreter can be named with
# `make gate PYTHON=/path/to/python`.

PYTHON ?= .venv/bin/python
PYTEST_WORKERS ?= 3

# The checks never send traces: a test of a graph on a fake model is not a run worth recording, and a
# shell that holds a LangSmith key would otherwise spend the project's monthly trace allowance.
export LANGSMITH_TRACING = false
export LANGCHAIN_TRACING_V2 = false
# The browser tests fail, rather than skip, when no browser can start.
export REQUIRE_BROWSER = 1
# The regulation tests fail, rather than skip, when SS1/23 has not been fetched.
export REQUIRE_REGULATIONS = 1

.PHONY: serve offline lint test schemas-check examples-check selftest planted-faults dataset-check policy-measures regulations-check notebook gate

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

# One pytest run per workspace member, each with its own import path, so topics whose packages
# share a name (each topic has a `utils`) never meet on one path. A new topic is one more line.
test: regulations-check
	$(PYTHON) -m pytest -q -n $(PYTEST_WORKERS) -o "pythonpath=fsi_common" fsi_common/tests
	$(PYTHON) -m pytest -q -n $(PYTEST_WORKERS) -o "pythonpath=fsi_common 01_kyc_agent" 01_kyc_agent/tests
	$(PYTHON) -m pytest -q -n $(PYTEST_WORKERS) -o "pythonpath=fsi_common 03_document_summary_agent" 03_document_summary_agent/tests
	$(PYTHON) -m pytest -q -n $(PYTEST_WORKERS) -o "pythonpath=fsi_common 02_transaction_monitoring_agent" 02_transaction_monitoring_agent/tests

# The record schemas must match what the record types export, byte for byte.
schemas-check:
	PYTHONPATH=fsi_common $(PYTHON) -m fsi_common.export_schemas --check

# The example files must be what the example code builds, byte for byte.
examples-check:
	PYTHONPATH=fsi_common $(PYTHON) -m fsi_common.examples.build --check

# The validator must catch every planted invalid example for its declared reason.
selftest:
	PYTHONPATH=fsi_common $(PYTHON) -m fsi_common.validate --selftest

# The evaluators must catch every planted fault, each lowering only the measures declared for it.
planted-faults:
	cd 01_kyc_agent && PYTHONPATH=../fsi_common $(abspath $(PYTHON)) -m evals.planted_faults
	cd 03_document_summary_agent && PYTHONPATH=../fsi_common $(abspath $(PYTHON)) -m evals.planted_faults
	cd 02_transaction_monitoring_agent && PYTHONPATH=../fsi_common $(abspath $(PYTHON)) -m evals.planted_faults

# The evaluation dataset must be what the reference labels and the document build, byte for byte.
dataset-check:
	cd 01_kyc_agent && PYTHONPATH=../fsi_common $(abspath $(PYTHON)) -m evals.build_dataset --check
	cd 03_document_summary_agent && PYTHONPATH=../fsi_common $(abspath $(PYTHON)) -m evals.build_dataset --check
	cd 02_transaction_monitoring_agent && PYTHONPATH=../fsi_common $(abspath $(PYTHON)) -m evals.build_dataset --check

# The policy measures: the planted faults must each lower their measure, then the figures print for the
# seed matches of the run the measures read. A bundle folder is measured with
# `python -m evals.policy_measures <folder>`.
policy-measures:
	cd 03_document_summary_agent && PYTHONPATH=../fsi_common $(abspath $(PYTHON)) -m evals.policy_measures --selftest
	cd 03_document_summary_agent && PYTHONPATH=../fsi_common $(abspath $(PYTHON)) -m evals.policy_measures --seed-matches evals/data/policy_seed_matches.jsonl --require-all

# The notebook must run top to bottom on the recorded model calls, with no key and no live call.
notebook:
	NOTEBOOK_RUN=1 MODEL_BACKEND=replay $(PYTHON) -m pytest -q -o "pythonpath=fsi_common 01_kyc_agent" 01_kyc_agent/tests/notebook
	NOTEBOOK_RUN=1 MODEL_BACKEND=replay $(PYTHON) -m pytest -q -o "pythonpath=fsi_common 03_document_summary_agent" 03_document_summary_agent/tests/notebook
	NOTEBOOK_RUN=1 MODEL_BACKEND=replay $(PYTHON) -m pytest -q -o "pythonpath=fsi_common 02_transaction_monitoring_agent" 02_transaction_monitoring_agent/tests/notebook

# The reviewer's application, on APP_HOST and APP_PORT (default 0.0.0.0:4803). Its runs, decisions
# and drafts are kept in files under APP_STATE_DIR, a folder of the repository that git ignores. One
# topic is served by the application's own process; two or more are each served by a process of their own.
APP_STATE_DIR ?= $(CURDIR)/.app-state
serve:
	APP_STATE_DIR=$(APP_STATE_DIR) PYTHONPATH=fsi_common:03_document_summary_agent $(PYTHON) -m fsi_common.app

# The offline edition: the application's pages for the recorded run, in one HTML file.
# With several topics built, each is read in a process of its own and one file is written for the topic named.
OFFLINE_OUT ?= build/compliance-brief-offline.html
offline:
	PYTHONPATH=fsi_common:03_document_summary_agent $(PYTHON) -m fsi_common.app.offline --topic compliance-brief --out $(OFFLINE_OUT)

# The three regulations must read into the units pinned for their digests, each unit accounted for.
# DORA and the AI Act are held in the repository; SS1/23 is fetched and cached when absent, and
# its reader needs poppler's pdftotext.
regulations-check:
	cd 03_document_summary_agent && PYTHONPATH=../fsi_common:. $(abspath $(PYTHON)) -m context.regulations check

gate: lint regulations-check test schemas-check examples-check selftest planted-faults dataset-check notebook
