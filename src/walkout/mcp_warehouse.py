"""Reads the warehouse through the official ClickHouse MCP server.

The agent never talks to ClickHouse directly. It runs the same validated SQL
the evaluation harness runs, but every statement travels over stdio to
`mcp-clickhouse`, which holds the credentials and answers in read-only mode.

The MCP client is asynchronous and the analysis pipeline is not, so one event
loop runs on a daemon thread for the life of the process and the session lives
on it. Starting a subprocess per query would be simpler and would also add a
second of latency to each of the dozen queries a single investigation makes.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import shutil
import sys
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import ClickHouseConfig, clickhouse
from .queries import load as load_query
from .warehouse import Row, render

SERVER_COMMAND = "mcp-clickhouse"
STARTUP_TIMEOUT_SEC = 60.0
QUERY_TIMEOUT_SEC = 180.0


class McpError(RuntimeError):
    """Raised when the MCP server refuses or fails a call."""


def server_command() -> str:
    """Absolute path to the MCP server executable.

    Prefer the one installed alongside the interpreter that is running us: on a
    host with several Pythons, whichever `mcp-clickhouse` happens to be first on
    PATH may belong to a different environment.
    """
    beside_interpreter = Path(sys.executable).parent / SERVER_COMMAND
    if beside_interpreter.exists():
        return str(beside_interpreter)
    found = shutil.which(SERVER_COMMAND)
    if found:
        return found
    raise McpError(
        f"{SERVER_COMMAND} is not installed. run: pip install -e '.[mcp]'"
    )


def server_env(config: ClickHouseConfig) -> dict[str, str]:
    """Environment for the server subprocess.

    The credentials are passed explicitly rather than inherited so the server
    connects to the cluster this process is configured for, whatever happens to
    be exported in the shell.
    """
    inherited = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")
        if key in os.environ
    }
    return {
        **inherited,
        "CLICKHOUSE_ENABLED": "true",
        "CLICKHOUSE_HOST": config.host,
        "CLICKHOUSE_PORT": str(config.port),
        "CLICKHOUSE_USER": config.username,
        "CLICKHOUSE_PASSWORD": config.password,
        "CLICKHOUSE_SECURE": "true" if config.secure else "false",
        "CLICKHOUSE_DATABASE": config.database,
    }


class McpWarehouse:
    """A Warehouse backed by a long-lived mcp-clickhouse session."""

    def __init__(self, config: ClickHouseConfig | None = None) -> None:
        self._config = config or clickhouse()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._lock = threading.Lock()

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Launch the server and complete the MCP handshake. Idempotent."""
        with self._lock:
            if self._session is not None:
                return
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=loop.run_forever, name="walkout-mcp", daemon=True
            )
            thread.start()
            self._loop, self._thread = loop, thread
            try:
                self._session = self._await(self._connect(), STARTUP_TIMEOUT_SEC)
            except Exception:
                self._shutdown_loop()
                raise
            atexit.register(self.close)

    async def _connect(self) -> ClientSession:
        stack = AsyncExitStack()
        params = StdioServerParameters(
            command=server_command(), args=[], env=server_env(self._config)
        )
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._stack = stack
        return session

    def close(self) -> None:
        """Shut the session and the server subprocess down."""
        with self._lock:
            if self._session is None:
                return
            stack, self._stack, self._session = self._stack, None, None
            if stack is not None and self._loop is not None:
                try:
                    self._await(stack.aclose(), STARTUP_TIMEOUT_SEC)
                except Exception:  # noqa: BLE001 - never fail a teardown
                    pass
            self._shutdown_loop()

    def _shutdown_loop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop, self._thread = None, None

    def _await(self, coro: Any, timeout: float) -> Any:
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def __enter__(self) -> "McpWarehouse":
        self.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # -- queries ---------------------------------------------------------

    def call(self, tool: str, arguments: dict[str, Any]) -> str:
        """Call any tool the server exposes and return its text payload."""
        self.start()
        assert self._session is not None
        result = self._await(
            self._session.call_tool(tool, arguments), QUERY_TIMEOUT_SEC
        )
        payload = "\n".join(
            block.text for block in result.content if getattr(block, "text", None)
        )
        if result.is_error:
            raise McpError(f"{tool} failed: {payload}")
        return payload

    def run_sql(self, sql: str) -> list[Row]:
        """Run one SELECT through the MCP server and return rows as dicts."""
        payload = self.call("run_query", {"query": sql})
        try:
            body = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise McpError(f"unreadable response: {payload[:400]}") from exc
        if isinstance(body, dict) and "error" in body:
            raise McpError(str(body["error"]))
        columns, rows = body["columns"], body["rows"]
        return [dict(zip(columns, row)) for row in rows]

    def run_named(self, name: str, params: dict[str, Any]) -> list[Row]:
        """Run one of sql/queries/*.sql with its parameters rendered inline."""
        from .clickhouse import DIM_SLOT, check_dimension

        sql = load_query(name)
        params = dict(params)
        dim = params.pop("dim", None)
        if DIM_SLOT in sql:
            if dim is None:
                raise ValueError(f"query {name!r} needs a `dim` parameter")
            sql = sql.replace(DIM_SLOT, check_dimension(dim))
        return self.run_sql(render(sql, params))
