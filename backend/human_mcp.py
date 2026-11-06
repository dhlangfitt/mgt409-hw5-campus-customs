"""The human side's MCP connection: the server in --approver mode.

Only backend/main.py uses this, for dashboard reads and for the decisions a
human makes (approve or reject). It is never given to an agent: agents connect
through mcp_connection.py, which refuses approver mode.
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from .config import MCP_CONFIG, MCP_SERVER_NAME, PROJECT_ROOT


class McpUnavailable(RuntimeError):
    pass


def build_approver_client() -> Client:
    entry = json.loads(MCP_CONFIG.read_text())["mcpServers"][MCP_SERVER_NAME]
    transport = StdioTransport(
        command=entry["command"],
        args=[*entry.get("args", []), "--approver"],
        env={"PATH": os.environ.get("PATH", ""), **entry.get("env", {})},
        cwd=str(PROJECT_ROOT),
        keep_alive=True,
    )
    return Client(transport)


async def call(client: Client, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call one tool and return its envelope ({ok, data, ...} or {ok: false, error})."""
    try:
        result = await client.call_tool(tool, args or {}, raise_on_error=False)
    except Exception as exc:  # transport or server process failure
        raise McpUnavailable(f"MCP server call {tool} failed: {type(exc).__name__}: {exc}") from exc
    if result.is_error or result.structured_content is None:
        text = result.content[0].text if result.content else "no detail"
        raise McpUnavailable(f"MCP tool {tool} failed: {text}")
    return result.structured_content
