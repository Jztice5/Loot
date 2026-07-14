VENV ?= .venv
PYTHON := $(VENV)/bin/python

.PHONY: setup test compile context-check check run

$(PYTHON):
	python3 -m venv $(VENV)

setup: $(PYTHON)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e '.[dev]'

test: $(PYTHON)
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -p 'test_*.py'

compile: $(PYTHON)
	$(PYTHON) -m compileall -q src tests scripts

context-check: $(PYTHON)
	$(PYTHON) scripts/check_context.py

check: context-check compile test

run: $(PYTHON)
	$(PYTHON) main.py
