"""What defines one agent: its name, prompt file, MCP tools and output type.

Each agent's definition lives in its own module (boss.py, inventory.py, ...).
team.py turns these definitions into PydanticAI agents and wires them together.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import AgentName

# Tools that exist only when the MCP server runs in approver mode. No agent may
# list them; the check below fails at import time if one ever does.
HUMAN_ONLY_TOOLS = frozenset({"execute_approved_payment", "reject_payment_request", "decide_purchase_request", "add_human_note"})


@dataclass(frozen=True)
class RoleSpec:
    name: AgentName
    title: str
    prompt_file: str
    mcp_tools: frozenset[str]
    output_type: type
    expertise: str  # one line, shown to colleagues so they know when to ask this agent

    def __post_init__(self) -> None:
        leaked = self.mcp_tools & HUMAN_ONLY_TOOLS
        if leaked:
            raise ValueError(f"{self.name} must not have human-only tools: {sorted(leaked)}")
