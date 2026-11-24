# Checks for the repository. Every target runs only commands inside this folder.
# After `uv sync --all-packages` the defaults below use .venv; another interpreter can be named with
# `make gate PYTHON=/path/to/python`.

PYTHON ?= .venv/bin/python
PYTEST_WORKERS ?= 3

.PHONY: lint test schemas-check examples-check selftest gate

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

gate: lint test schemas-check examples-check selftest
