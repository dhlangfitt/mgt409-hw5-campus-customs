import { useEffect, useRef } from "react";
import { AGENTS, TOOL_LABEL, identity } from "../agents";
import type { ActivityEvent, AgentName } from "../types";
import { clock } from "../usePoll";
import { AgentBadge } from "./AgentBadge";

type Obj = Record<string, unknown>;
const asObj = (v: unknown): Obj => (v && typeof v === "object" ? (v as Obj) : {});
const label = (agent: string) => AGENTS[agent as AgentName]?.label ?? identity(agent).label;

/** The shift log: one run at a time, read top to bottom like a conversation on the shop floor. */
export function ShiftLog({ events, running, loading }: { events: ActivityEvent[]; running: boolean; loading: boolean }) {
  const endRef = useRef<HTMLDivElement>(null);
  const count = events.length;
  useEffect(() => {
    if (running) endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [count, running]);

  if (loading && events.length === 0) return <div className="log"><div className="skeleton line" /><div className="skeleton line short" /></div>;
  if (events.length === 0) {
    return (
      <div className="log empty-log">
        <p className="empty-title">Quiet on the floor.</p>
        <p className="empty">Nobody has worked this ticket yet. Send it to the team and their conversation will appear here as it happens.</p>
      </div>
    );
  }

  const runs: { runId: string; events: ActivityEvent[] }[] = [];
  for (const e of events) {
    const last = runs[runs.length - 1];
    if (last && last.runId === e.run_id) last.events.push(e);
    else runs.push({ runId: e.run_id, events: [e] });
  }

  return (
    <div className="log" aria-live="polite">
      {runs.map((r) => (
        <section key={r.runId + r.events[0].seq} className="log-run">
          {r.events[0].event !== "run_started" && (
            <div className="log-divider"><span>{r.runId === "human" ? "Your decisions" : r.runId === "system" ? "System" : "Earlier activity (not a full ticket run)"} · {clock(r.events[0].ts)}</span></div>
          )}
          {r.events.map((e) => <LogLine key={e.seq} e={e} />)}
        </section>
      ))}
      {running && (
        <div className="log-line typing"><span className="typing-dots"><i /><i /><i /></span> the team is working…</div>
      )}
      <div ref={endRef} />
    </div>
  );
}

function LogLine({ e }: { e: ActivityEvent }) {
  const args = asObj(e.args);
  const result = asObj(e.result);
  const depth = Math.max(0, (e.chain?.length ?? 1) - 1);
  const style = { ["--hue" as string]: identity(e.agent).hue, ["--depth" as string]: depth };

  switch (e.event) {
    case "run_started":
      return <div className="log-divider"><span>Run started · {clock(e.ts)}</span><code>{e.run_id}</code></div>;
    case "agent_started":
      if (String(args.prompt ?? "").startsWith("Request from")) return null; // the hand-off card already shows it
      return <div className="log-line" style={style}><AgentBadge agent={e.agent} size="sm" /><span className="log-text">picked up the ticket</span><time>{clock(e.ts)}</time></div>;
    case "model_step":
      return null; // the tool calls and messages below say the same thing more usefully
    case "mcp_tool_call": {
      const ok = result.ok !== false;
      const err = asObj(result.error);
      return (
        <div className={`log-line tool ${ok ? "" : "bad"}`} style={style}>
          <AgentBadge agent={e.agent} size="sm" showLabel={false} />
          <span className="log-text">{TOOL_LABEL[e.action ?? ""] ?? "used a tool"}</span>
          <details className="tool-chip">
            <summary><code>{e.action}</code>{ok ? " ✓" : " ✗"}</summary>
            <pre>{JSON.stringify({ args: e.args, result: e.result }, null, 1)}</pre>
          </details>
          {!ok && <span className="log-err">{String(err.message ?? "error")}</span>}
          <time>{clock(e.ts)}</time>
        </div>
      );
    }
    case "delegation":
      return (
        <div className="handoff" style={style}>
          <div className="handoff-head">
            <AgentBadge agent={e.agent} size="sm" />
            <span className="handoff-arrow" aria-label="hands off to">⟶</span>
            <AgentBadge agent={String(args.colleague)} size="sm" />
            <time>{clock(e.ts)}</time>
          </div>
          <blockquote>{String(args.request ?? "")}</blockquote>
        </div>
      );
    case "delegation_refused":
      return (
        <div className="log-line warn" style={style}>
          <AgentBadge agent={e.agent} size="sm" showLabel={false} />
          <span className="log-text">couldn't hand off to {label(String(args.colleague))}: {e.reason}</span>
          <time>{clock(e.ts)}</time>
        </div>
      );
    case "agent_finished": {
      const status = String(result.status ?? "");
      return (
        <div className="speech" style={style}>
          <div className="speech-head">
            <AgentBadge agent={e.agent} size="sm" />
            {status && <span className={`pill pill-${status}`}>{status.replace(/_/g, " ")}</span>}
            <time>{clock(e.ts)}</time>
          </div>
          <p>{String(result.summary ?? "")}</p>
          {e.reason && e.agent !== "boss" && <p className="speech-why">Handing back: {e.reason}</p>}
        </div>
      );
    }
    case "run_finished":
      return <div className="log-divider end"><span>Run finished · {String(result.final_status ?? "").replace(/_/g, " ")} · {clock(e.ts)}</span></div>;
    case "human_decision":
      return <div className="log-line human" style={style}><AgentBadge agent={e.agent} size="sm" /><span className="log-text">{e.action}: {e.reason}</span><time>{clock(e.ts)}</time></div>;
    case "limit_reached":
    case "error":
    case "tool_call_blocked":
      return <div className="log-line bad" style={style}><AgentBadge agent={e.agent} size="sm" showLabel={false} /><span className="log-text">{e.summary}</span><time>{clock(e.ts)}</time></div>;
    default:
      return <div className="log-line" style={style}><span className="log-text">{e.summary}</span><time>{clock(e.ts)}</time></div>;
  }
}
