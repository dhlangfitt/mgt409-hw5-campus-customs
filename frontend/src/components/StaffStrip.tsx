import { AGENT_ORDER, AGENTS, TOOL_LABEL } from "../agents";
import type { ActivityEvent, AgentName } from "../types";

export type StaffState = { state: "idle" | "working" | "waiting" | "done" | "not_called"; note?: string };

/** Work out each agent's current state from the latest run's events. */
export function staffStates(events: ActivityEvent[], running: boolean): Record<AgentName, StaffState> {
  const out = Object.fromEntries(AGENT_ORDER.map((a) => [a, { state: running ? "idle" : "not_called" }])) as Record<AgentName, StaffState>;
  const lastRun = [...events].reverse().find((e) => e.event === "run_started")?.run_id;
  if (!lastRun) return Object.fromEntries(AGENT_ORDER.map((a) => [a, { state: "idle" }])) as Record<AgentName, StaffState>;
  for (const e of events) {
    if (e.run_id !== lastRun || !(e.agent in AGENTS)) continue;
    const a = e.agent as AgentName;
    const args = (e.args ?? {}) as Record<string, string>;
    const result = (e.result ?? {}) as Record<string, string>;
    if (e.event === "agent_started") out[a] = { state: "working", note: "reading the request" };
    if (e.event === "mcp_tool_call") out[a] = { state: "working", note: TOOL_LABEL[e.action ?? ""] ?? e.action ?? "" };
    if (e.event === "delegation") out[a] = { state: "waiting", note: `waiting on ${AGENTS[args.colleague as AgentName]?.label ?? args.colleague}` };
    if (e.event === "agent_finished") out[a] = { state: "done", note: (result.status ?? "").replace(/_/g, " ") };
  }
  if (!running) for (const a of AGENT_ORDER) if (out[a].state === "idle") out[a] = { state: "not_called" };
  return out;
}

const STATE_LABEL = { idle: "On shift", working: "Working", waiting: "Waiting", done: "Reported", not_called: "Not needed" };

/** The five staff badges, lit up when they're involved in the current run. */
export function StaffStrip({ states }: { states: Record<AgentName, StaffState> }) {
  return (
    <div className="staff" aria-label="Agent team">
      {AGENT_ORDER.map((name) => {
        const a = AGENTS[name];
        const s = states[name];
        return (
          <div key={name} className={`staff-card state-${s.state}`} style={{ ["--hue" as string]: a.hue }}>
            <span className="staff-disc" aria-hidden>{a.glyph}</span>
            <span className="staff-text">
              <span className="staff-name">{a.label}</span>
              <span className="staff-role">{a.role}</span>
            </span>
            <span className="staff-state">
              <span className="dot" />{STATE_LABEL[s.state]}
              {s.note && <span className="staff-note">{s.note}</span>}
            </span>
          </div>
        );
      })}
    </div>
  );
}
