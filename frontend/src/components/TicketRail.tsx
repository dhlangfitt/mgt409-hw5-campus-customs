import { TICKET_TYPE_LABEL } from "../agents";
import type { TicketSummary } from "../types";

export type Stamp = { text: string; tone: "open" | "working" | "needs" | "progress" | "resolved" };

export function stampFor(t: TicketSummary, runningTicketId: number | null): Stamp {
  if (runningTicketId === t.id || t.latest_run?.status === "running") return { text: "Working", tone: "working" };
  if (t.is_resolved) return { text: "Resolved", tone: "resolved" };
  if (t.pending_approval_requests > 0 || t.status === "awaiting_approval") return { text: "Needs you", tone: "needs" };
  if (t.status === "in_progress") return { text: "In progress", tone: "progress" };
  return { text: "Open", tone: "open" };
}

/** The ticket rail: each ticket is a paper receipt clipped to the counter. */
export function TicketRail({ tickets, selectedId, onSelect, runningTicketId, loading }: {
  tickets: TicketSummary[] | null; selectedId: number | null; onSelect: (id: number) => void; runningTicketId: number | null; loading: boolean;
}) {
  if (!tickets && loading) {
    return <div className="rail">{[0, 1, 2].map((i) => <div key={i} className="receipt skeleton" />)}</div>;
  }
  if (!tickets || tickets.length === 0) {
    return <div className="rail"><p className="empty">No tickets on the board.</p></div>;
  }
  return (
    <div className="rail" role="listbox" aria-label="Tickets">
      {tickets.map((t) => {
        const stamp = stampFor(t, runningTicketId);
        const outcome = t.latest_run?.outcome;
        return (
          <button
            key={t.id}
            role="option"
            aria-selected={t.id === selectedId}
            className={`receipt ${t.id === selectedId ? "selected" : ""} tone-${stamp.tone}`}
            onClick={() => onSelect(t.id)}
          >
            <span className="receipt-top">
              <span className="receipt-no">#{t.id}</span>
              <span className={`stamp stamp-${stamp.tone}`}>{stamp.text}</span>
            </span>
            <span className="receipt-type">{TICKET_TYPE_LABEL[t.type] ?? t.type}</span>
            <span className="receipt-subject">{t.subject}</span>
            <span className="receipt-from">from {t.requester}</span>
            {(t.pending_approval_requests > 0 || t.message_drafts > 0) && (
              <span className="receipt-chips">
                {t.pending_approval_requests > 0 && <span className="chip chip-needs">✎ {t.pending_approval_requests} to sign</span>}
                {t.message_drafts > 0 && <span className="chip">✉ {t.message_drafts} draft{t.message_drafts > 1 ? "s" : ""}</span>}
              </span>
            )}
            {t.is_resolved && outcome && <span className="receipt-summary">{outcome.summary}</span>}
          </button>
        );
      })}
    </div>
  );
}
