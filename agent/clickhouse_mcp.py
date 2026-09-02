"""ClickHouse MCP toolset for the ADK agent (the partner integration headline).

Wires the official ClickHouse MCP server (`mcp-clickhouse`) into the ADK agent as
a live toolset. When connected, the Librarian answers catalog questions through
the partner's own MCP tools (`list_databases`, `list_tables`, `run_select_query`
/ `run_query`) — the concrete "integrates a Partner Entity's MCP" the hackathon
requires.

Writes (ingest / archive) stay on `clickhouse-connect` because the official
server is read-only. The agent is not given Python read tools, so Gemini has to
go through MCP for stats, duplicate waste, and reuse search.
"""
from __future__ import annotations

import os
import sys

from .config import get_settings


def mcp_command() -> tuple[str, list[str]]:
    """Prefer the preinstalled module; fall back to uvx if pip didn't land it."""
    import importlib.util

    if importlib.util.find_spec("mcp_clickhouse") is not None:
        return sys.executable, ["-m", "mcp_clickhouse.main"]
    return "uvx", ["mcp-clickhouse"]


def mcp_server_env() -> dict[str, str]:
    s = get_settings()
    return {
        "CLICKHOUSE_HOST": s.ch_host,
        "CLICKHOUSE_PORT": str(s.ch_port),
        "CLICKHOUSE_USER": s.ch_user,
        "CLICKHOUSE_PASSWORD": s.ch_password,
        "CLICKHOUSE_SECURE": "true" if s.ch_secure else "false",
        "CLICKHOUSE_DATABASE": s.ch_database,
        # stdio transport (ADK MCPToolset). Don't let a leftover HTTP setting win.
        "CLICKHOUSE_MCP_SERVER_TRANSPORT": "stdio",
    }


def mcp_status() -> dict:
    """Cheap health snapshot — does not spawn the MCP subprocess."""
    s = get_settings()
    installed = False
    error = ""
    try:
        import importlib.util

        installed = importlib.util.find_spec("mcp_clickhouse") is not None
        if not installed:
            error = "mcp-clickhouse is not installed"
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:240]
    command, args = mcp_command()
    enabled = s.use_clickhouse_mcp
    return {
        "enabled": enabled,
        "installed": installed,
        "ok": bool(enabled and installed and s.ch_host),
        "command": " ".join([command, *args]),
        "error": error,
    }


def build_clickhouse_mcp_toolset():
    """Return an ADK McpToolset backed by mcp-clickhouse, or None if disabled.

    The server reads CLICKHOUSE_* env vars (same names as our .env), so we pass
    the resolved settings straight through.
    """
    if not get_settings().use_clickhouse_mcp:
        print("[clickhouse-mcp] USE_CLICKHOUSE_MCP is false; agent will have no catalog reads")
        return None

    try:
        from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
        from mcp import StdioServerParameters
    except Exception as exc:  # ADK/mcp not installed or incompatible
        print(f"[clickhouse-mcp] toolset unavailable ({exc})")
        return None

    command, args = mcp_command()
    env = {**os.environ, **mcp_server_env()}
    try:
        return McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=command,
                    args=args,
                    env=env,
                ),
                timeout=30.0,
            ),
        )
    except Exception as exc:
        print(f"[clickhouse-mcp] failed to start server ({exc})")
        return None
