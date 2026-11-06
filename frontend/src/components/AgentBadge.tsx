import { identity } from "../agents";

/** A staff name badge: coloured glyph disc + name. Used everywhere an agent appears. */
export function AgentBadge({ agent, size = "md", showLabel = true }: { agent: string; size?: "sm" | "md" | "lg"; showLabel?: boolean }) {
  const id = identity(agent);
  return (
    <span className={`badge badge-${size}`} style={{ ["--hue" as string]: id.hue }} title={`${id.label} · ${id.role}`}>
      <span className="badge-disc" aria-hidden>{id.glyph}</span>
      {showLabel && <span className="badge-name">{id.label}</span>}
    </span>
  );
}
