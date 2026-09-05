"""The Walkout agent.

A multi-step investigator built on Gemini and the Agent Development Kit. It
reads a warehouse of playback telemetry through the official ClickHouse MCP
server, watches the film through Gemini's video understanding, and reconciles
the two into a cause an editor, a localization manager, or a streaming engineer
can act on.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
from mcp import StdioServerParameters

from ..config import clickhouse, google
from ..gemini import RETRY_OPTIONS
from ..mcp_warehouse import server_command, server_env
from .prompts import INSTRUCTION
from .tools import find_walkouts, investigate_walkout, watch_scene

# The model may ask the warehouse anything it likes, but only reads. The server
# runs read-only by default; naming the tools it may reach is the second lock.
READ_ONLY_TOOLS = ["run_query", "list_tables", "list_databases"]

MCP_STARTUP_TIMEOUT_SEC = 60.0



def clickhouse_toolset() -> MCPToolset:
    """Direct read access to the cluster through the official MCP server.

    The fixed tools cover the investigation itself. This is for the questions
    that come after it -- the ones a person asks when they have read the
    finding and want to know one more thing.
    """
    return MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=server_command(), args=[], env=server_env(clickhouse())
            ),
            timeout=MCP_STARTUP_TIMEOUT_SEC,
        ),
        tool_filter=READ_ONLY_TOOLS,
    )


def build_agent() -> LlmAgent:
    """Assemble the agent. Called at import so `adk web` and the API share it."""
    return LlmAgent(
        name="walkout",
        model=Gemini(model=google().model, retry_options=RETRY_OPTIONS),
        description=(
            "Diagnoses why an audience stops watching a title, separating "
            "editorial problems from delivery and localization ones."
        ),
        instruction=INSTRUCTION,
        tools=[find_walkouts, investigate_walkout, watch_scene, clickhouse_toolset()],
    )


root_agent = build_agent()
