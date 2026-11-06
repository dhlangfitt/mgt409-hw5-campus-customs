"""The Boss: reads tickets, decides who's needed, makes the final call."""

from ..models import TicketOutcome
from .role import RoleSpec

ROLE = RoleSpec(
    name="boss",
    title="Boss",
    prompt_file="boss.md",
    mcp_tools=frozenset({"list_ticket_board", "get_ticket_details", "list_pending_approvals", "update_ticket_status"}),
    output_type=TicketOutcome,
    expertise="Owns each ticket: decides who works on it, makes judgement calls (e.g. discounts), and closes it.",
)
