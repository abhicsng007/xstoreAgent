"""ClickHouse MCP toolset for the ADK agent (the partner integration headline).

Wires the official ClickHouse MCP server (`mcp-clickhouse`) into the ADK agent as
a live toolset. When connected, the Librarian agent can issue ClickHouse queries
through the partner's own MCP server — the concrete "integrates a Partner Entity's
MCP" the hackathon asks for.

If the MCP server can't start (missing `uvx`, network, etc.), the agent still has
the direct `clickhouse_client` function tools, so ingestion and search keep
working. Enable/disable via USE_CLICKHOUSE_MCP in the environment.
"""
from __future__ import annotations

import os

from .config import get_settings


def build_clickhouse_mcp_toolset():
    """Return an ADK MCPToolset backed by mcp-clickhouse, or None if disabled.

    The server reads CLICKHOUSE_* env vars (same names as our .env), so we pass
    the resolved settings straight through.
    """
    if os.getenv("USE_CLICKHOUSE_MCP", "true").lower() != "true":
        return None

    try:
        from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
        from mcp import StdioServerParameters
    except Exception as exc:  # ADK/mcp not installed or incompatible
        print(f"[clickhouse-mcp] toolset unavailable ({exc}); using function tools")
        return None

    s = get_settings()
    server_env = {
        "CLICKHOUSE_HOST": s.ch_host,
        "CLICKHOUSE_PORT": str(s.ch_port),
        "CLICKHOUSE_USER": s.ch_user,
        "CLICKHOUSE_PASSWORD": s.ch_password,
        "CLICKHOUSE_SECURE": "true" if s.ch_secure else "false",
        "CLICKHOUSE_DATABASE": s.ch_database,
    }
    try:
        return MCPToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="uvx",
                    args=["mcp-clickhouse"],
                    env={**os.environ, **server_env},
                ),
            )
        )
    except Exception as exc:
        print(f"[clickhouse-mcp] failed to start server ({exc}); using function tools")
        return None
