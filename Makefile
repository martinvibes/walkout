.PHONY: help install doctor load simulate eval test clean

VENV ?= .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

help:
	@echo "make install    create the venv and install walkout"
	@echo "make doctor     check ClickHouse credentials and row counts"
	@echo "make load       apply sql/schema.sql to the cluster"
	@echo "make simulate   generate telemetry and insert it (250k sessions)"
	@echo "make eval       grade the pipeline against planted ground truth"
	@echo "make test       run the unit tests"

$(VENV):
	python3 -m venv $(VENV)

install: $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -e ".[dev]"

doctor:
	$(PY) -c "from walkout.cli import doctor; raise SystemExit(doctor())"

load:
	$(PY) -c "from walkout.cli import load; raise SystemExit(load())"

simulate:
	$(PY) -m walkout.cli --clickhouse --sessions $(or $(SESSIONS),250000)

eval:
	$(PY) -c "from walkout.cli import evaluate; raise SystemExit(evaluate())"

test:
	$(PY) -m pytest -q

clean:
	rm -rf $(VENV) data/*.csv.gz .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
