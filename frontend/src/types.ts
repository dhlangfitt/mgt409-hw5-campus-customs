// Mirrors backend/models.py ("API shapes"). The dashboard only knows these
// shapes, never table names or MCP tools.

export type AgentName = "boss" | "inventory" | "accounting" | "facilities" | "customer_service";
export type RunStatus = "running" | "completed" | "failed";
export type ApprovalState = "proposed" | "awaiting_approval" | "approved" | "executed" | "rejected" | "failed";

export interface TicketOutcome {
  ticket_id: number;
  final_status: "resolved" | "awaiting_approval" | "needs_human_input" | "could_not_complete";
  summary: string;
  agents_consulted: AgentName[];
  decisions: string[];
  payment_request_ids: number[];
  purchase_request_ids: number[];
  draft_ids: number[];
  next_steps_for_human: string[];
}

export interface RunSummary {
  run_id: string;
  ticket_id: number;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  outcome: TicketOutcome | null;
  error: string | null;
  activity_url: string;
}

export interface TicketSummary {
  id: number;
  type: string;
  requester: string;
  subject: string;
  status: string;
  is_resolved: boolean;
  created_at: string;
  pending_approval_requests: number;
  message_drafts: number;
  latest_run: RunSummary | null;
}

export interface TicketList {
  shop_today: string | null;
  tickets: TicketSummary[];
}

export interface ApprovalItem {
  kind: "payment" | "purchase";
  id: number;
  ticket_id: number | null;
  state: ApprovalState;
  description: string;
  amount: number | null;
  requested_by: string;
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  payment_id: number | null;
  vendor_on_hold: boolean | null;
}

export interface Draft {
  id: number;
  recipient_type: string;
  recipient_name: string;
  subject: string;
  author: string;
  status: string;
  created_at: string;
}

export interface TicketDetail {
  shop_today: string | null;
  ticket: {
    id: number; type: string; requester: string; subject: string; sku: string | null; size: string | null;
    qty: number | null; lease_id: number | null; invoice_id: number | null; status: string; notes: string | null; created_at: string;
  };
  linked_records: Record<string, Record<string, unknown> | null>;
  notes: { author: string; status_after: string | null; note: string; created_at: string }[];
  message_drafts: Draft[];
  approvals: ApprovalItem[];
  runs: RunSummary[];
}

export interface ActivityEvent {
  seq: number;
  ts: string;
  run_id: string;
  ticket_id: number | null;
  agent: string;
  event: string;
  action: string | null;
  summary: string;
  chain: string[];
  args: unknown;
  result: unknown;
  reason: string | null;
  usage: Record<string, number> | null;
}

export interface ActivityPage {
  events: ActivityEvent[];
  next_since: number;
  run: RunSummary | null;
  busy: string | null;
}

export interface CashResponse {
  shop_today: string | null;
  account: string;
  balance: number;
  balance_as_of: string;
  accounts: { account: string; balance: number; balance_as_of: string }[];
  obligations_on_record: { source_table: string; id: number; payee: string | null; amount: number; description: string | null; due_date: string; is_overdue: boolean | null; days_overdue: number | null; days_until_due: number | null }[];
  balance_after_all_obligations: number | null;
  payments: { id: number; kind: string; ref_id: number; amount: number; account: string; paid_at: string; approved_by: string }[];
}

export interface DecisionResponse {
  approval: ApprovalItem;
  executed: boolean;
  message: string;
  payment: Record<string, unknown> | null;
  balance_before: number | null;
  balance_after: number | null;
}

export interface Health {
  status: "ok" | "degraded";
  model: string;
  portkey_key_configured: boolean;
  mcp_connected: boolean;
  busy: string | null;
}
