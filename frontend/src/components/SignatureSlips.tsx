import { useState } from "react";
import { api, ApiError } from "../api";
import type { ApprovalItem } from "../types";
import { money } from "../usePoll";
import { AgentBadge } from "./AgentBadge";

const STATE_COPY: Record<ApprovalItem["state"], { tag: string; tone: string; line: (a: ApprovalItem) => string }> = {
  proposed:          { tag: "Being prepared", tone: "proposed", line: () => "Agents are still working on this ticket. Nothing has been paid." },
  awaiting_approval: { tag: "Not paid · needs your signature", tone: "awaiting", line: (a) => a.kind === "payment" ? "No money has left the account. It moves only if you approve." : "Nothing has been ordered. Approving records the decision only." },
  executed:          { tag: "Paid", tone: "executed", line: (a) => `${money(a.amount)} left the account · payment #${a.payment_id} · signed by ${a.decided_by}` },
  approved:          { tag: "Approved · recorded", tone: "approved", line: (a) => `Signed by ${a.decided_by}. No vendor contacted and no money moved.` },
  rejected:          { tag: "Rejected · not paid", tone: "rejected", line: (a) => `Rejected by ${a.decided_by}: ${a.decision_note ?? ""}` },
  failed:            { tag: "Refused · not paid", tone: "failed", line: (a) => a.decision_note ?? "Execution was refused. No money moved." },
};

/** A signature slip: the one place a human turns a prepared request into a decision. */
export function SignatureSlip({ item, signer, onDecided, disabledReason }: {
  item: ApprovalItem; signer: string; onDecided: () => void; disabledReason: string | null;
}) {
  const [confirming, setConfirming] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const copy = STATE_COPY[item.state];
  const open = item.state === "awaiting_approval";
  const blocked = !signer.trim() ? "Enter your name under “Signing as” first." : disabledReason;

  async function decide(decision: "approve" | "reject") {
    setBusy(true); setError(null);
    try {
      const r = await api.decide(item.kind, item.id, decision, signer.trim(), note.trim());
      setResult(r.message);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false); setConfirming(false); setRejecting(false);
      onDecided();
    }
  }

  return (
    <article className={`slip slip-${copy.tone}`}>
      <header className="slip-head">
        <span className="slip-kind">{item.kind === "payment" ? "Payment request" : "Purchase request"} #{item.id}</span>
        <span className={`slip-tag tag-${copy.tone}`}>{copy.tag}</span>
      </header>
      <div className="slip-amount">{money(item.amount)}{item.kind === "purchase" && <small> est.</small>}</div>
      <p className="slip-desc">{item.description}</p>
      <p className="slip-line">{copy.line(item)}</p>
      <footer className="slip-meta">
        <span>Prepared by <AgentBadge agent={item.requested_by} size="sm" /></span>
        {item.ticket_id && <span>ticket #{item.ticket_id}</span>}
        {item.vendor_on_hold && <span className="chip chip-warn">vendor on hold</span>}
      </footer>

      {open && !result && (
        <div className="slip-actions">
          {!confirming && !rejecting && (
            <>
              <button className="btn btn-approve" disabled={!!blocked || busy} onClick={() => setConfirming(true)}>
                {item.kind === "payment" ? `Approve & pay ${money(item.amount)}` : "Approve purchase"}
              </button>
              <button className="btn btn-ghost" disabled={!!blocked || busy} onClick={() => setRejecting(true)}>Reject</button>
            </>
          )}
          {confirming && (
            <div className="confirm">
              <p>{item.kind === "payment"
                ? <>Pay <b>{money(item.amount)}</b> from checking now? The balance is re-checked at the moment of payment.</>
                : <>Approve this purchase? This records your decision; nothing is ordered and no money moves.</>}</p>
              <button className="btn btn-approve" disabled={busy} onClick={() => decide("approve")}>{busy ? "Working…" : item.kind === "payment" ? "Yes, pay it" : "Yes, approve"}</button>
              <button className="btn btn-ghost" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
            </div>
          )}
          {rejecting && (
            <div className="confirm">
              <label>Reason for rejecting
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. wait until rent is paid" autoFocus />
              </label>
              <button className="btn btn-reject" disabled={busy || !note.trim()} onClick={() => decide("reject")}>{busy ? "Working…" : "Reject"}</button>
              <button className="btn btn-ghost" disabled={busy} onClick={() => setRejecting(false)}>Cancel</button>
            </div>
          )}
          {blocked && <p className="slip-hint">{blocked}</p>}
        </div>
      )}
      {result && <p className="slip-result">{result}</p>}
      {error && <p className="slip-error" role="alert">{error}</p>}
    </article>
  );
}
