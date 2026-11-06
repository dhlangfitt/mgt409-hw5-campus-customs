import type {
  ActivityPage, ApprovalItem, CashResponse, DecisionResponse, Health, RunSummary, TicketDetail, TicketList,
} from "./types";

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

/** Every failure becomes an ApiError. `offline` means the backend could not be reached at all. */
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, unknown> = {}) {
    super(message);
  }
  get offline() { return this.code === "offline"; }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
      signal: init?.signal ?? AbortSignal.timeout(15000),
    });
  } catch {
    throw new ApiError(0, "offline", `Can't reach the backend at ${API_BASE}.`);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const err = body?.error ?? {};
    throw new ApiError(res.status, err.code ?? "http_error", err.message ?? `HTTP ${res.status}`, err.details ?? {});
  }
  return body as T;
}

const post = <T,>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/api/health"),
  tickets: () => request<TicketList>("/api/tickets"),
  ticket: (id: number) => request<TicketDetail>(`/api/tickets/${id}`),
  startRun: (id: number) => post<{ run: RunSummary; message: string }>(`/api/tickets/${id}/runs`),
  activity: (ticketId: number, since: number) => request<ActivityPage>(`/api/activity?ticket_id=${ticketId}&since=${since}&limit=500`),
  approvals: () => request<ApprovalItem[]>("/api/approvals"),
  decide: (kind: "payment" | "purchase", id: number, decision: "approve" | "reject", decided_by: string, note?: string) =>
    post<DecisionResponse>(`/api/approvals/${kind}/${id}/decision`, { decision, decided_by, note: note || null }),
  addNote: (ticketId: number, author: string, note: string) =>
    post<{ message: string }>(`/api/tickets/${ticketId}/notes`, { author, note }),
  cash: () => request<CashResponse>("/api/cash"),
  reset: () => post<{ message: string; balance: number | null }>("/api/admin/reset", { confirm: "RESET" }),
};
