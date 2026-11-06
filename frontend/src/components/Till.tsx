import { useEffect, useRef, useState } from "react";
import type { ApprovalItem, CashResponse } from "../types";
import { money } from "../usePoll";

/** The till: what is actually in the account, kept apart from what is merely awaiting approval. */
export function Till({ cash, approvals, error }: { cash: CashResponse | null; approvals: ApprovalItem[]; error: string | null }) {
  const [flash, setFlash] = useState(false);
  const last = useRef<number | null>(null);
  useEffect(() => {
    if (cash && last.current !== null && cash.balance !== last.current) {
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 2400);
      return () => clearTimeout(t);
    }
    if (cash) last.current = cash.balance;
  }, [cash]);
  useEffect(() => { if (cash) last.current = cash.balance; }, [cash?.balance]);

  const waiting = approvals.filter((a) => a.kind === "payment" && (a.state === "awaiting_approval" || a.state === "proposed"));
  const waitingTotal = waiting.reduce((s, a) => s + (a.amount ?? 0), 0);

  return (
    <section className="till" aria-label="Checking account">
      <div className="till-label">In checking now</div>
      {cash ? (
        <div className={`till-balance ${flash ? "flash" : ""}`}>{money(cash.balance)}</div>
      ) : (
        <div className="till-balance skeleton-text">{error ? "—" : "…"}</div>
      )}
      <div className="till-asof">{cash ? `as of ${cash.balance_as_of} (shop date)` : error ?? "loading"}</div>
      {cash && (
        <dl className="till-rows">
          <div><dt>Waiting for signature <em>(not paid)</em></dt><dd>{waiting.length ? `${money(waitingTotal)} · ${waiting.length}` : "none"}</dd></div>
          <div><dt>If every bill on record were paid</dt><dd className={(cash.balance_after_all_obligations ?? 0) < 0 ? "neg" : ""}>{money(cash.balance_after_all_obligations)}</dd></div>
        </dl>
      )}
      {cash && cash.obligations_on_record.length > 0 && (
        <details className="till-more">
          <summary>Bills on record ({cash.obligations_on_record.length})</summary>
          <ul>{cash.obligations_on_record.map((o) => (
            <li key={o.source_table + o.id}><span>{o.payee} · {o.description}</span><span>{money(o.amount)}</span>
              <small>{o.is_overdue ? `${o.days_overdue} days overdue` : `due in ${o.days_until_due} days`}</small></li>
          ))}</ul>
        </details>
      )}
      {cash && (
        <div className="till-paid">
          <div className="till-sub">Paid out</div>
          {cash.payments.length === 0 ? <p className="empty">No payments yet.</p> : (
            <ul>{cash.payments.map((p) => (
              <li key={p.id}><span>#{p.id} · {p.kind} {p.ref_id}</span><span className="out">−{money(p.amount)}</span><small>signed by {p.approved_by} · {p.paid_at}</small></li>
            ))}</ul>
          )}
        </div>
      )}
    </section>
  );
}
