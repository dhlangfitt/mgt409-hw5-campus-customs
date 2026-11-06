"""Customer Service: what customers are told, always as drafts."""

from ..models import AgentReport
from .role import RoleSpec

ROLE = RoleSpec(
    name="customer_service",
    title="Customer Service",
    prompt_file="customer_service.md",
    mcp_tools=frozenset({"get_ticket_details", "get_stock_and_price_quote", "save_draft_message"}),
    output_type=AgentReport,
    expertise="Drafts replies to customers (never sent) once the facts and decisions are known.",
)
