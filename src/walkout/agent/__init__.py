"""The Walkout agent package.

`root_agent` is the name the ADK tooling looks for, so `adk web` and `adk run`
find this agent without further configuration.
"""

from .agent import build_agent, root_agent

__all__ = ["build_agent", "root_agent"]
