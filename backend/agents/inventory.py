"""Inventory: stock levels, vendors, lead times and restock requests."""

from ..models import AgentReport
from .role import RoleSpec

ROLE = RoleSpec(
    name="inventory",
    title="Inventory",
    prompt_file="inventory.md",
    mcp_tools=frozenset({
        "get_ticket_details", "get_stock_and_price_quote", "list_vendors_with_status",
        "get_invoice_and_vendor_status", "check_cash_for_amount", "prepare_purchase_request",
    }),
    output_type=AgentReport,
    expertise="Stock on hand by size, which vendor can restock and when (lead times, shipping holds), restock purchase requests.",
)
