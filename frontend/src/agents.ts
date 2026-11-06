import type { AgentName } from "./types";

/** Each agent's visual identity: one hue, one glyph, a role title. */
export interface AgentIdentity {
  name: AgentName;
  label: string;
  role: string;
  glyph: string;
  hue: string;
}

export const AGENTS: Record<AgentName, AgentIdentity> = {
  boss:             { name: "boss",             label: "Boss",             role: "Shift lead",    glyph: "★", hue: "#ff4fa3" },
  accounting:       { name: "accounting",       label: "Accounting",       role: "The ledger",    glyph: "$", hue: "#f5b83d" },
  inventory:        { name: "inventory",        label: "Inventory",        role: "Stockroom",     glyph: "▦", hue: "#35d0b4" },
  facilities:       { name: "facilities",       label: "Facilities",       role: "Premises",      glyph: "⌂", hue: "#a98bff" },
  customer_service: { name: "customer_service", label: "Customer Service", role: "Front counter", glyph: "❝", hue: "#5fb2ff" },
};

export const AGENT_ORDER: AgentName[] = ["boss", "accounting", "inventory", "facilities", "customer_service"];

export function identity(agent: string): { label: string; glyph: string; hue: string; role: string } {
  if (agent in AGENTS) return AGENTS[agent as AgentName];
  if (agent.startsWith("human:")) return { label: agent.slice(6), glyph: "✎", hue: "#9be7b9", role: "Human" };
  return { label: agent || "System", glyph: "·", hue: "#8d8a99", role: "System" };
}

export const TICKET_TYPE_LABEL: Record<string, string> = {
  customer_order: "Customer order",
  rent_notice: "Rent notice",
  price_override: "Discount request",
};

export const TOOL_LABEL: Record<string, string> = {
  list_ticket_board: "read the board",
  get_ticket_details: "read the ticket",
  get_invoice_and_vendor_status: "checked invoice & vendor",
  get_rent_payment_status: "checked the rent",
  get_stock_and_price_quote: "checked stock & price",
  list_vendors_with_status: "checked vendors",
  check_cash_for_amount: "checked cash",
  get_cash_position: "checked cash",
  list_pending_approvals: "checked approvals",
  prepare_payment_request: "prepared a payment request",
  prepare_purchase_request: "prepared a purchase request",
  save_draft_message: "saved a draft",
  update_ticket_status: "updated the ticket",
};
