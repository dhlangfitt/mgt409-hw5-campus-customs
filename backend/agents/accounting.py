"""Accounting: invoices, cash, margins and payment requests."""

from ..models import AgentReport
from .role import RoleSpec

ROLE = RoleSpec(
    name="accounting",
    title="Accounting",
    prompt_file="accounting.md",
    mcp_tools=frozenset({
        "get_ticket_details", "get_invoice_and_vendor_status", "get_rent_payment_status",
        "check_cash_for_amount", "get_stock_and_price_quote", "list_vendors_with_status",
        "list_pending_approvals", "prepare_payment_request",
        # Added in Problem 7: with lean routing Accounting is often the only specialist
        # on a restock question, and the server already allows it to prepare purchases.
        "prepare_purchase_request",
    }),
    output_type=AgentReport,
    expertise="Invoices, cash on hand, whether a payment fits, stock and vendor holds, margins and discount floors; the only agent that prepares payment requests, and can prepare restock requests.",
)
