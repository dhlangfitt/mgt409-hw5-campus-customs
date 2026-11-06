"""Append-only audit trail: backend/output/audit_trail.json.

The file is a JSON array. New events are appended in place: the closing "]" is
replaced by ",<event>]", so earlier events are never rewritten or removed, and
the file stays valid JSON. A lock stops two writers from interleaving.

Entries are kept small: long strings are cut, long lists shortened, deep
structures summarised, and anything that looks like a secret is redacted.
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from typing import Any

from .config import audit_trail_path
from .models import AuditEvent, TeamDeps, TicketRun

MAX_STRING = 600  # long enough for an agent's summary or hand-off request to read in full
MAX_LIST = 8
MAX_DEPTH = 4
SECRET_HINTS = ("api_key", "apikey", "secret", "password", "authorization", "token")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def compact(value: Any, depth: int = 0) -> Any:
    """A shortened, secret-free copy of value that's safe to log."""
    if depth >= MAX_DEPTH:
        return "…"
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if any(hint in str(key).lower() for hint in SECRET_HINTS) and "tokens" not in str(key).lower():
                out[key] = "[redacted]"
            else:
                out[key] = compact(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        items = [compact(item, depth + 1) for item in value[:MAX_LIST]]
        if len(value) > MAX_LIST:
            items.append(f"… {len(value) - MAX_LIST} more")
        return items
    if isinstance(value, str) and len(value) > MAX_STRING:
        return value[:MAX_STRING] + f"… ({len(value)} chars)"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return compact(str(value), depth)


def summarise_tool_result(result: Any) -> Any:
    """The useful part of an MCP envelope: ok/error, plus a compact copy of data."""
    if isinstance(result, dict) and "ok" in result:
        if not result["ok"]:
            return {"ok": False, "error": compact(result.get("error"))}
        return {"ok": True, "data": compact(result.get("data")), "not_in_database": compact(result.get("not_in_database"))}
    return compact(result)


def append(event: AuditEvent) -> None:
    path = audit_trail_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event.model_dump(exclude_none=True), ensure_ascii=False, default=str)
    with open(path, "a+b") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if size == 0:
                fh.write(f"[\n{line}\n]\n".encode())
                return
            # Find the final "]" and write the new event in front of it.
            pos = size - 1
            fh.seek(pos)
            while pos > 0 and fh.read(1) in (b"\n", b" ", b"\r", b"\t"):
                pos -= 1
                fh.seek(pos)
            fh.seek(pos)
            if fh.read(1) != b"]":
                raise RuntimeError(f"{path} is not a JSON array; refusing to append to it.")
            fh.truncate(pos)
            fh.seek(pos)
            fh.write(f",\n{line}\n]\n".encode())
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def usage_snapshot(usage: Any) -> dict[str, int] | None:
    if usage is None:
        return None
    return {
        "requests": getattr(usage, "requests", 0),
        "tool_calls": getattr(usage, "tool_calls", 0),
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
    }


def log(
    event: str,
    *,
    run: TicketRun,
    agent: str,
    deps: TeamDeps | None = None,
    action: str | None = None,
    args: Any = None,
    result: Any = None,
    reason: str | None = None,
    usage: Any = None,
) -> None:
    append(
        AuditEvent(
            ts=_now(),
            run_id=run.run_id,
            ticket_id=run.ticket_id,
            agent=agent,
            chain=list(deps.chain) if deps else [],
            event=event,  # type: ignore[arg-type]
            action=action,
            args=compact(args) if args is not None else None,
            result=result,
            reason=reason,
            usage=usage_snapshot(usage),
        )
    )


def log_human(event: str, *, ticket_id: int | None, actor: str, action: str, args: Any = None,
              result: Any = None, reason: str | None = None) -> None:
    """Log something a human did through the API (an approval decision, a reset)."""
    append(
        AuditEvent(
            ts=_now(),
            run_id="human" if event == "human_decision" else "system",
            ticket_id=ticket_id,
            agent=f"human:{actor}" if event == "human_decision" else actor,
            event=event,  # type: ignore[arg-type]
            action=action,
            args=compact(args) if args is not None else None,
            result=compact(result) if result is not None else None,
            reason=reason,
        )
    )
