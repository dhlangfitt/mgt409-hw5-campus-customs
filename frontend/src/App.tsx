import { useEffect, useMemo, useRef, useState } from "react";
import { AGENTS, TICKET_TYPE_LABEL } from "./agents";
import { api, API_BASE, ApiError } from "./api";
import { AgentBadge } from "./components/AgentBadge";
import { ShiftLog } from "./components/ShiftLog";
import { SignatureSlip } from "./components/SignatureSlips";
import { StaffStrip, staffStates } from "./components/StaffStrip";
import { stampFor, TicketRail } from "./components/TicketRail";
import { Till } from "./components/Till";
import type { ActivityEvent, AgentName, TicketDetail } from "./types";
import { money, usePoll } from "./usePoll";

const SIGNER_KEY = "campus-customs-signer";

export default function App() {
  const health = usePoll(api.health, 4000);
  const offline = !!health.error?.offline;
  const busy = health.data?.busy ?? null;

  // The run this tab just started, until the server confirms it has finished.
  const [localRun, setLocalRun] = useState<{ ticketId: number; runId: string } | null>(null);
  const tickets = usePoll(api.tickets, localRun ? 1500 : 5000, [!!localRun]);
  const runningTicketId =
    tickets.data?.tickets.find((t) => t.latest_run?.status === "running")?.id ??
    (busy?.match(/on ticket (\d+)/) ? Number(busy.match(/on ticket (\d+)/)![1]) : null) ??
    localRun?.ticketId ?? null;

  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => {
    if (selected === null && tickets.data?.tickets.length) setSelected(tickets.data.tickets[0].id);
  }, [tickets.data, selected]);
  const selectedRunning = selected !== null && runningTicketId === selected;

  const detail = usePoll<TicketDetail | null>(() => (selected ? api.ticket(selected) : Promise.resolve(null)), selectedRunning ? 2000 : 6000, [selected, selectedRunning]);
  const approvals = usePoll(api.approvals, runningTicketId ? 2000 : 4000, [!!runningTicketId]);
  const cash = usePoll(api.cash, 5000);

  // Activity feed for the selected ticket: accumulate new events with a cursor.
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [eventsLoading, setEventsLoading] = useState(true);
  const cursor = useRef(0);
  useEffect(() => {  // switching tickets starts a fresh feed
    setEvents([]); cursor.current = 0; setEventsLoading(true);
  }, [selected]);
  useEffect(() => {  // polling only adds events; a run ending or a dropped connection never clears them
    if (selected === null) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const page = await api.activity(selected, cursor.current);
        if (cancelled) return;
        cursor.current = page.next_since;
        if (page.events.length) setEvents((prev) => [...prev, ...page.events]);
      } catch { /* the connection banner covers this */ }
      finally { if (!cancelled) { setEventsLoading(false); timer = setTimeout(tick, selectedRunning ? 1200 : 5000); } }
    };
    tick();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [selected, selectedRunning]);

  // When a run finishes, refresh everything that it may have changed.
  const wasRunning = useRef(false);
  useEffect(() => {
    const isRunning = !!runningTicketId;
    if (wasRunning.current && !isRunning) {
      setLocalRun(null);
      tickets.refresh(); detail.refresh(); approvals.refresh(); cash.refresh();
    }
    wasRunning.current = isRunning;
  }, [runningTicketId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // clear the optimistic flag as soon as the server reports that exact run as finished
    if (!localRun) return;
    const latest = tickets.data?.tickets.find((t) => t.id === localRun.ticketId)?.latest_run;
    if (latest && latest.run_id === localRun.runId && latest.status !== "running") setLocalRun(null);
  }, [localRun, tickets.data]);

  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  async function start() {
    if (!selected) return;
    setStarting(true); setStartError(null);
    try {
      const started = await api.startRun(selected);
      setLocalRun({ ticketId: selected, runId: started.run.run_id });
      tickets.refresh(); health.refresh();
    } catch (e) {
      setStartError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }

  async function resetAll() {
    if (!window.confirm("Start fresh? This replaces the working database with the original (balance back to $3,400, all requests and drafts cleared). The activity history is kept.")) return;
    try {
      await api.reset();
      setEvents([]); cursor.current = 0;
      tickets.refresh(); detail.refresh(); approvals.refresh(); cash.refresh(); health.refresh();
    } catch (e) {
      window.alert(e instanceof ApiError ? e.message : String(e));
    }
  }

  const [signer, setSigner] = useState(() => localStorage.getItem(SIGNER_KEY) ?? "");
  useEffect(() => { localStorage.setItem(SIGNER_KEY, signer); }, [signer]);

  const allApprovals = approvals.data ?? [];
  const needsSignature = allApprovals.filter((a) => a.state === "awaiting_approval" || a.state === "proposed");
  const decided = allApprovals.filter((a) => !(a.state === "awaiting_approval" || a.state === "proposed"));
  const staff = useMemo(() => staffStates(events, selectedRunning), [events, selectedRunning]);
  const ticketSummary = tickets.data?.tickets.find((t) => t.id === selected) ?? null;
  const stamp = ticketSummary ? stampFor(ticketSummary, runningTicketId) : null;
  // Ignore detail left over from the previously selected ticket while the new one loads.
  const ticketDetail = detail.data && detail.data.ticket.id === selected ? detail.data : null;
  const latestRun = ticketDetail?.runs[0] ?? ticketSummary?.latest_run ?? null;
  const outcome = latestRun?.status === "completed" ? latestRun.outcome : null;

  const startBlocked = offline ? "The backend is offline."
    : !health.data?.portkey_key_configured ? "No PORTKEY_API_KEY is configured on the backend."
    : busy ? `Busy: ${busy}`
    : ticketSummary?.is_resolved ? "This ticket is resolved." : null;

  return (
    <div className={`desk ${offline ? "is-offline" : ""}`}>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">Campus Customs</span>
          <span className="brand-sub">operations desk</span>
        </div>
        <div className="topbar-mid">
          <span className="shopdate">Shop date <b>{tickets.data?.shop_today ?? "—"}</b></span>
          <span className={`conn ${offline ? "down" : health.data?.status === "ok" ? "up" : "warn"}`}>
            <span className="dot" />{offline ? "Backend offline" : health.data ? (health.data.status === "ok" ? "Connected" : "Degraded") : "Connecting…"}
          </span>
          {busy && <span className="busy-chip"><span className="spinner" />{busy.startsWith("agent run") ? `Team working on #${runningTicketId}` : busy}</span>}
        </div>
        <div className="topbar-right">
          <span className="mini-till" title="Balance in checking (actual money)">Checking <b>{money(cash.data?.balance)}</b></span>
          <button className="btn btn-quiet" onClick={resetAll} disabled={offline || !!busy}>Start fresh</button>
        </div>
      </header>

      {offline && (
        <div className="banner" role="alert">
          <b>Can't reach the backend at {API_BASE}.</b> Showing the last data received; retrying every few seconds.
          Start it from <code>hw5/backend</code> with <code>uvicorn main:app --reload --port 8000</code>.
        </div>
      )}
      {!offline && health.data && !health.data.mcp_connected && (
        <div className="banner warn" role="alert">The backend is up but its MCP server isn't responding. Shop data may be stale.</div>
      )}

      <main className="counter">
        <aside className="col-rail">
          <h2 className="col-title">Ticket rail</h2>
          {tickets.error && !tickets.data && !offline && <p className="error">{tickets.error.message}</p>}
          <TicketRail tickets={tickets.data?.tickets ?? null} selectedId={selected} onSelect={setSelected} runningTicketId={runningTicketId} loading={tickets.loading} />
        </aside>

        <section className="col-floor">
          {!ticketSummary ? (
            <div className="floor-empty"><p className="empty-title">Pick a ticket from the rail.</p></div>
          ) : (
            <>
              <div className="ticket-head">
                <div>
                  <div className="ticket-kicker">#{ticketSummary.id} · {TICKET_TYPE_LABEL[ticketSummary.type] ?? ticketSummary.type} · from {ticketSummary.requester}</div>
                  <h1 className="ticket-title">{ticketSummary.subject}</h1>
                  {ticketDetail?.ticket.notes && <p className="ticket-note">“{ticketDetail.ticket.notes}”</p>}
                  <LinkedFacts detail={ticketDetail} />
                </div>
                <div className="ticket-cta">
                  {stamp && <span className={`stamp big stamp-${stamp.tone}`}>{stamp.text}</span>}
                  <button className="btn btn-go" onClick={start} disabled={!!startBlocked || starting}>
                    {selectedRunning ? "Team at work…" : starting ? "Sending…" : latestRun ? "Send to the team again" : "Send to the team"}
                  </button>
                  {startBlocked && !selectedRunning && <span className="cta-hint">{startBlocked}</span>}
                  {startError && <span className="cta-error" role="alert">{startError}</span>}
                </div>
              </div>

              <StaffStrip states={staff} />

              {outcome && (
                <section className={`outcome outcome-${outcome.final_status}`}>
                  <div className="outcome-head">
                    <span className="outcome-label">{outcome.final_status === "resolved" ? "Resolved" : "Boss's wrap-up"}</span>
                    <span className={`pill pill-${outcome.final_status}`}>{outcome.final_status.replace(/_/g, " ")}</span>
                    <span className="outcome-who">{["boss", ...outcome.agents_consulted].filter((v, i, a) => a.indexOf(v) === i).map((a) => <AgentBadge key={a} agent={a} size="sm" showLabel={false} />)}</span>
                  </div>
                  <p>{outcome.summary}</p>
                  {outcome.decisions.length > 0 && <ul className="outcome-list">{outcome.decisions.map((d, i) => <li key={i}>{d}</li>)}</ul>}
                  {outcome.next_steps_for_human.length > 0 && (
                    <div className="outcome-next"><b>For you:</b><ul>{outcome.next_steps_for_human.map((d, i) => <li key={i}>{d}</li>)}</ul></div>
                  )}
                </section>
              )}
              {latestRun?.status === "failed" && <section className="outcome outcome-could_not_complete"><b>The run failed.</b> <span>{latestRun.error}</span></section>}

              {ticketDetail && (
                <NotesPanel
                  notes={ticketDetail.notes}
                  signer={signer}
                  disabled={offline ? "The backend is offline." : busy ? `Busy: ${busy}` : null}
                  onSave={async (text) => { await api.addNote(ticketDetail.ticket.id, signer.trim(), text); detail.refresh(); }}
                />
              )}

              {ticketDetail && ticketDetail.message_drafts.length > 0 && (
                <section className="drafts">
                  <h3>Drafts on the board <span className="muted">(never sent)</span></h3>
                  {ticketDetail.message_drafts.map((d) => (
                    <div key={d.id} className="draft"><AgentBadge agent={d.author} size="sm" showLabel={false} /><span>To {d.recipient_name} ({d.recipient_type}): <b>{d.subject}</b></span><span className="chip">draft · not sent</span></div>
                  ))}
                </section>
              )}

              <h2 className="col-title log-title">Shift log</h2>
              <ShiftLog events={events} running={selectedRunning} loading={eventsLoading} />
            </>
          )}
        </section>

        <aside className="col-till">
          <Till cash={cash.data} approvals={allApprovals} error={cash.error?.message ?? null} />
          <section className="signatures">
            <div className="sig-head">
              <h2 className="col-title">Needs your signature {needsSignature.length > 0 && <span className="count">{needsSignature.length}</span>}</h2>
              <label className="signer">Signing as
                <input value={signer} onChange={(e) => setSigner(e.target.value)} placeholder="your name" aria-label="Your name for approvals" />
              </label>
            </div>
            {approvals.loading && !approvals.data ? <div className="skeleton slip-skel" /> : needsSignature.length === 0 ? (
              <p className="empty">Nothing waiting for a signature. When an agent prepares a payment or purchase, it lands here — and nothing is paid until you approve it.</p>
            ) : needsSignature.map((a) => (
              <SignatureSlip key={a.kind + a.id} item={a} signer={signer}
                disabledReason={a.state === "proposed" ? "Wait for the team to finish this ticket." : busy ? `Busy: ${busy}` : null}
                onDecided={() => { approvals.refresh(); cash.refresh(); tickets.refresh(); detail.refresh(); }} />
            ))}
            {decided.length > 0 && (
              <details className="history">
                <summary>Decided ({decided.length})</summary>
                {decided.map((a) => <SignatureSlip key={a.kind + a.id} item={a} signer={signer} disabledReason={null} onDecided={() => undefined} />)}
              </details>
            )}
          </section>
        </aside>
      </main>
      <footer className="foot">
        Agents: {Object.values(AGENTS).map((a) => <AgentBadge key={a.name} agent={a.name as AgentName} size="sm" />)}
        <span className="muted">· model {health.data?.model ?? "—"} via Portkey · data via MCP</span>
      </footer>
    </div>
  );
}

function NotesPanel({ notes, signer, disabled, onSave }: {
  notes: TicketDetail["notes"]; signer: string; disabled: string | null; onSave: (text: string) => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const humanNotes = notes.filter((n) => n.author.startsWith("human:"));
  const blocked = !signer.trim() ? "Enter your name under “Signing as” first." : disabled;
  async function save() {
    setSaving(true); setError(null); setSaved(null);
    try { await onSave(text.trim()); setText(""); setSaved("Saved. Send the ticket to the team again so the Boss can act on it."); }
    catch (e) { setError(e instanceof ApiError ? e.message : String(e)); }
    finally { setSaving(false); }
  }
  return (
    <section className="notes">
      <h3>Notes from you to the team</h3>
      {humanNotes.length === 0 ? <p className="empty">No notes yet. Use this for decisions the team asked you for, such as a discount level.</p> : (
        <ul>{humanNotes.map((n, i) => <li key={i}><AgentBadge agent={n.author} size="sm" /> <span>{n.note}</span></li>)}</ul>
      )}
      <div className="note-form">
        <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Approve 15% off; supply the 8 in stock now and the rest later" rows={2} aria-label="Note to the team" />
        <button className="btn btn-ghost" disabled={!!blocked || saving || !text.trim()} onClick={save}>{saving ? "Saving…" : "Leave note"}</button>
      </div>
      {blocked && <p className="slip-hint">{blocked}</p>}
      {saved && <p className="slip-result">{saved}</p>}
      {error && <p className="slip-error" role="alert">{error}</p>}
    </section>
  );
}

function LinkedFacts({ detail }: { detail: TicketDetail | null }) {
  if (!detail) return null;
  const facts: string[] = [];
  const s = detail.linked_records.stock as Record<string, unknown> | undefined;
  const inv = detail.linked_records.invoice as Record<string, unknown> | undefined;
  const lease = detail.linked_records.lease as Record<string, unknown> | undefined;
  const t = detail.ticket;
  if (t.sku) facts.push(`${t.qty ?? "?"} × ${t.sku} size ${t.size}`);
  if (s) facts.push(`${s.on_hand} in stock (${s.location})`);
  if (inv) facts.push(`invoice ${inv.id}: ${money(inv.amount as number)} to ${inv.vendor}, ${inv.status}, due ${inv.due_date}`);
  if (lease) facts.push(`lease ${lease.id}: ${money(lease.monthly_rent as number)} rent due ${lease.next_due}`);
  if (!facts.length) return null;
  return <ul className="facts">{facts.map((f) => <li key={f}>{f}</li>)}</ul>;
}
