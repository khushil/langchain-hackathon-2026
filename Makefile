# Checks for the repository. Every target runs only commands inside this folder.
# After `uv sync --all-packages` the defaults below use .venv; another interpreter can be named with
# `make gate PYTHON=/path/to/python`.

PYTHON ?= .venv/bin/python
PYTEST_WORKERS ?= 3

.PHONY: lint test schemas-check examples-check selftest gate

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

test:
	$(PYTHON) -m pytest -q -n $(PYTEST_WORKERS)

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
