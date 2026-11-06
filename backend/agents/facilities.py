"""Facilities: the shop's lease, rent and landlord."""

from ..models import AgentReport
from .role import RoleSpec

ROLE = RoleSpec(
    name="facilities",
    title="Facilities",
    prompt_file="facilities.md",
    mcp_tools=frozenset({"get_ticket_details", "get_rent_payment_status", "list_pending_approvals", "save_draft_message"}),
    output_type=AgentReport,
    expertise="The lease, rent due dates and the landlord relationship (landlord messages are drafts only).",
)
