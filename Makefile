PYTHON ?= .venv/bin/python
RUFF := $(PYTHON) -m ruff
PYTEST := $(PYTHON) -m pytest
PRE_COMMIT := $(PYTHON) -m pre_commit
PRE_COMMIT_HOME ?= .cache/pre-commit

.PHONY: install-dev fmt lint test check validate-pre-commit

install-dev:
	$(PYTHON) -m pip install --disable-pip-version-check -r requirements-dev.txt

fmt:
	$(RUFF) format .
	$(RUFF) check --fix .

lint:
	$(RUFF) format --check .
	$(RUFF) check .

test:
	$(PYTEST)

check: lint test

validate-pre-commit:
	PRE_COMMIT_HOME=$(PRE_COMMIT_HOME) $(PRE_COMMIT) validate-config
