.PHONY: help install mcp-server doctor load simulate eval eval-mcp agent serve test clean

VENV     ?= .venv
MCP_VENV ?= .venv-mcp
PY       := $(VENV)/bin/python
PIP      := $(VENV)/bin/pip

help:
	@echo "make install     create the venv and install walkout"
	@echo "make mcp-server  install the ClickHouse MCP server (its own venv)"
	@echo "make doctor      check ClickHouse credentials and row counts"
	@echo "make load        apply sql/schema.sql to the cluster"
	@echo "make simulate    generate telemetry and insert it (250k sessions)"
	@echo "make eval        grade the pipeline against planted ground truth"
	@echo "make eval-mcp    grade it through the ClickHouse MCP server instead"
	@echo "make agent       run the agent over sintel (TITLE=... to change)"
	@echo "make serve       run the web app on http://127.0.0.1:8000"
	@echo "make test        run the unit tests"

$(VENV):
	python3 -m venv $(VENV)

install: $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -e ".[dev]"

# The MCP server is built on fastmcp, which needs mcp 2.x, while ADK needs
# mcp 1.x. They are separate processes, so they get separate environments --
# which also keeps Walkout's own dependency tree Google-only.
$(MCP_VENV):
	python3 -m venv $(MCP_VENV)

mcp-server: $(MCP_VENV)
	$(MCP_VENV)/bin/pip install --quiet --upgrade pip
	$(MCP_VENV)/bin/pip install --quiet mcp-clickhouse
	@echo "clickhouse mcp server: $(MCP_VENV)/bin/mcp-clickhouse"

doctor:
	$(PY) -c "from walkout.cli import doctor; raise SystemExit(doctor())"

load:
	$(PY) -c "from walkout.cli import load; raise SystemExit(load())"

simulate:
	$(PY) -m walkout.cli --clickhouse --sessions $(or $(SESSIONS),250000)

eval:
	$(PY) -c "from walkout.cli import evaluate; raise SystemExit(evaluate())"

eval-mcp:
	$(PY) -c "import sys; from walkout.cli import evaluate; sys.exit(evaluate(['--mcp']))"

agent:
	$(PY) -c "import sys; from walkout.cli import agent; sys.exit(agent(['$(or $(TITLE),sintel)']))"

serve:
	$(PY) -c "from walkout.web.app import serve; raise SystemExit(serve())"

test:
	$(PY) -m pytest -q

clean:
	rm -rf $(VENV) $(MCP_VENV) data/*.csv.gz .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
