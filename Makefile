# Checks for the repository. Every target runs only commands inside this folder.
# After `uv sync --all-packages` the defaults below use .venv; another interpreter can be named with
# `make gate PYTHON=/path/to/python`.

PYTHON ?= .venv/bin/python
PYTEST_WORKERS ?= 3

# The checks never send traces: a test of a graph on a fake model is not a run worth recording, and a
# shell that holds a LangSmith key would otherwise spend the project's monthly trace allowance.
export LANGSMITH_TRACING = false
export LANGCHAIN_TRACING_V2 = false

.PHONY: lint test schemas-check examples-check selftest planted-faults dataset-check notebook gate

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

# One pytest run per workspace member, each with its own import path, so topics whose packages
# share a name (each topic has a `utils`) never meet on one path. A new topic is one more line.
test:
	$(PYTHON) -m pytest -q -n $(PYTEST_WORKERS) -o "pythonpath=fsi_common" fsi_common/tests
	$(PYTHON) -m pytest -q -n $(PYTEST_WORKERS) -o "pythonpath=fsi_common 03_document_summary_agent" 03_document_summary_agent/tests

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
	cd 03_document_summary_agent && PYTHONPATH=../fsi_common $(abspath $(PYTHON)) -m evals.planted_faults

# The evaluation dataset must be what the reference labels and the document build, byte for byte.
dataset-check:
	cd 03_document_summary_agent && PYTHONPATH=../fsi_common $(abspath $(PYTHON)) -m evals.build_dataset --check

# The notebook must run top to bottom on the recorded model calls, with no key and no live call.
notebook:
	NOTEBOOK_RUN=1 MODEL_BACKEND=replay $(PYTHON) -m pytest -q -o "pythonpath=fsi_common 03_document_summary_agent" 03_document_summary_agent/tests/notebook

gate: lint test schemas-check examples-check selftest planted-faults dataset-check notebook
