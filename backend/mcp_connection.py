"""The agents' only route to shop data: the campus-customs MCP server.

The connection is built from the project's mcp.json, so agents launch exactly
the server that was smoke-tested in Problem 4, in agent mode. This module
refuses a config that would start the server with --approver, so no agent can
ever reach the human-approval tools.

Every MCP call an agent makes passes through `_process_tool_call`, which:
  1. stamps the real agent name into requested_by / author / updated_by, so an
     agent can't act under another agent's name;
  2. enforces the per-ticket tool-call budget;
  3. writes the call and a compact result to the audit trail.
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from pydantic_ai import RunContext
from pydantic_ai.mcp import MCPToolset

from . import audit
from .config import MCP_CONFIG, MCP_SERVER_NAME, PROJECT_ROOT, ConfigError
from .models import TeamDeps

IDENTITY_ARGS = ("requested_by", "author", "updated_by")


def _server_entry() -> dict[str, Any]:
    config = json.loads(MCP_CONFIG.read_text())
    try:
        entry = config["mcpServers"][MCP_SERVER_NAME]
    except KeyError as exc:
        raise ConfigError(f"{MCP_CONFIG.name} has no '{MCP_SERVER_NAME}' server.") from exc
    if "--approver" in entry.get("args", []):
        raise ConfigError("The agents' MCP server must run in agent mode; remove --approver from mcp.json.")
    return entry


async def _process_tool_call(ctx: RunContext[TeamDeps], call_tool: Any, name: str, args: dict[str, Any]) -> Any:
    deps = ctx.deps
    run = deps.run
    args = dict(args)
    for key in IDENTITY_ARGS:
        if key in args:
            args[key] = deps.agent

    if run.mcp_tool_calls >= run.limits.max_tool_calls:
        reason = f"Tool-call budget for this ticket ({run.limits.max_tool_calls}) is used up."
        audit.log("tool_call_blocked", run=run, agent=deps.agent, deps=deps, action=name, args=args, reason=reason, usage=ctx.usage)
        return {"ok": False, "tool": name, "error": {"type": "budget_exhausted", "message": reason + " Report back with what you have."}}
    run.mcp_tool_calls += 1

    try:
        result = await call_tool(name, args)
    except Exception as exc:  # the server process or transport failed
        audit.log("error", run=run, agent=deps.agent, deps=deps, action=name, args=args, reason=f"{type(exc).__name__}: {exc}", usage=ctx.usage)
        raise
    audit.log(
        "mcp_tool_call",
        run=run,
        agent=deps.agent,
        deps=deps,
        action=name,
        args=args,
        result=audit.summarise_tool_result(result),
        usage=ctx.usage,
    )
    return result


def build_shop_toolset() -> MCPToolset[TeamDeps]:
    """One MCP connection, shared by the team. Each agent sees a filtered view of it."""
    entry = _server_entry()
    transport = StdioTransport(
        command=entry["command"],
        args=list(entry.get("args", [])),
        env={**{"PATH": os.environ.get("PATH", "")}, **entry.get("env", {})},
        cwd=str(PROJECT_ROOT),
    )
    return MCPToolset(Client(transport), process_tool_call=_process_tool_call, max_retries=1)
