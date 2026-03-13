PYTHON ?= .venv/bin/python
RUFF := $(PYTHON) -m ruff
PYTEST := $(PYTHON) -m pytest
MYPY := $(PYTHON) -m mypy
PRE_COMMIT := $(PYTHON) -m pre_commit
PRE_COMMIT_HOME ?= .cache/pre-commit

.PHONY: install-dev fmt lint test typecheck check validate-pre-commit

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

typecheck:
	$(MYPY)

check: lint test typecheck

validate-pre-commit:
	PRE_COMMIT_HOME=$(PRE_COMMIT_HOME) $(PRE_COMMIT) validate-config
