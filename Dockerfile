# Walkout
#
# Two Python environments on purpose. The application needs mcp 1.x, because
# that is what the Agent Development Kit pins; the official ClickHouse MCP
# server is built on fastmcp and needs mcp 2.x. They are separate processes
# that talk over stdio, so the conflict only exists if you insist on one
# interpreter for both.

FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The MCP server first: it changes least, so it stays cached across rebuilds.
RUN python -m venv /opt/mcp \
 && /opt/mcp/bin/pip install --no-cache-dir mcp-clickhouse
ENV WALKOUT_MCP_COMMAND=/opt/mcp/bin/mcp-clickhouse

# Dependencies before source, for the same reason.
COPY pyproject.toml README.md LICENSE ./
COPY src/walkout/__init__.py ./src/walkout/
RUN pip install --no-cache-dir -e .

COPY src ./src
COPY sql ./sql

# config.PROJECT_ROOT resolves to /app from src/walkout/config.py, which is why
# sql/ and data/ live beside the source rather than inside the package.
RUN mkdir -p /app/data/scene_readings

ENV HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=15s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",8000)}/api/health', timeout=10)"

CMD ["walkout-serve"]
