.PHONY: setup run review list test sample lint

PYTHON ?= python3
VENV := venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt
	cp -n .env.example .env || true
	@echo "Done. Edit .env if needed, then: ollama pull llama3.2:3b"

sample:
	$(PY) examples/generate_sample_docs.py

run:
	$(PY) scripts/run_pipeline.py

review:
	$(PY) scripts/run_pipeline.py --review

list:
	$(PY) scripts/run_pipeline.py --list

test:
	$(PY) -m pytest tests/ -v

lint:
	$(VENV)/bin/ruff check .

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache db
	find src scripts extract ingest validate load tests -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true