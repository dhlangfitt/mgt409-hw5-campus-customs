"""Campus Customs backend API: the one interface between the dashboard and the agent team.

Start it from the backend/ folder with the project's virtual environment active:

    uvicorn main:app --reload --port 8000

The dashboard never touches MCP or the database. This API:
  * reads shop data through the MCP server (approver mode, held only here);
  * starts agent runs (the agents get their own agent-mode MCP connection);
  * streams progress by polling the append-only audit trail with a cursor;
  * applies human approval decisions, where money only moves after a human approves;
  * resets the working database from the original.

One lock serialises everything that changes the working database: an agent run,
a human decision or a reset. While one is in progress, the others get
409 Conflict ("busy").

Updates while a ticket runs: the dashboard polls GET /api/activity?run_id=…&since=N
every 1–2 s and receives only new events. Polling was chosen over Server-Sent
Events or WebSockets because runs last tens of seconds, the audit trail is
already the record, and polling survives restarts and dropped connections with
no extra machinery.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:  # so `uvicorn main:app` works from backend/
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Path as PathParam, Query, Request, status  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from backend import audit  # noqa: E402
from backend.agents.team import Team  # noqa: E402
from backend.config import ConfigError, audit_trail_path, model_id  # noqa: E402
from backend.human_mcp import McpUnavailable, build_approver_client, call  # noqa: E402
from backend.models import (  # noqa: E402
    AGENT_NAMES,
    ActivityEvent,
    ActivityPage,
    ApprovalItem,
    ApprovalState,
    CashResponse,
    DecisionRequest,
    DecisionResponse,
    NoteRequest,
    ResetRequest,
    ResetResponse,
    RunSummary,
    StartRunResponse,
    TicketDetail,
    TicketList,
    TicketOutcome,
    TicketRun,
    TicketSummary,
)

ORIGINAL_DB = PROJECT_ROOT / "data" / "campus_customs.db"
WORKING_DB = PROJECT_ROOT / "data" / "campus_customs_new.db"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Errors: every failure is {"error": {"code", "message", "details"}}
# --------------------------------------------------------------------------- #


class ApiProblem(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code, self.code, self.message, self.details = status_code, code, message, details or {}


# How MCP tool errors map to HTTP
MCP_ERROR_STATUS = {"invalid_input": 422, "not_found": 404, "refused": 409, "database_unavailable": 503, "database_error": 500}


def _unwrap(envelope: dict[str, Any]) -> dict[str, Any]:
    if envelope.get("ok"):
        return envelope
    err = dict(envelope.get("error") or {})
    kind = err.pop("type", "error")
    message = err.pop("message", "The MCP tool failed.")
    code = err.get("reason", kind) if kind == "refused" else kind
    raise ApiProblem(MCP_ERROR_STATUS.get(kind, 500), code, message, err)


# --------------------------------------------------------------------------- #
# Application state
# --------------------------------------------------------------------------- #


class State:
    def __init__(self) -> None:
        # One writer at a time (agent run, human decision or reset). `busy` is the lock:
        # the API runs on one event loop thread, and check-then-set below has no await
        # between them, so two requests can't both take it.
        self.busy: str | None = None
        self.runs: dict[str, RunSummary] = {}
        self.tasks: set[asyncio.Task] = set()
        self.team: Team | None = None
        self.mcp = None                     # the human-side (approver-mode) MCP client

    def acquire_now(self, label: str) -> None:
        """Take the writer lock without waiting, or answer 409 Conflict."""
        if self.busy is not None:
            raise ApiProblem(409, "busy", f"Busy: {self.busy}. Try again when it has finished.", {"busy": self.busy})
        self.busy = label

    def release(self) -> None:
        self.busy = None

    def running_ticket_ids(self) -> set[int]:
        return {r.ticket_id for r in self.runs.values() if r.status == "running"}


state = State()


async def mcp(tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call a tool on the human-side MCP connection, reconnecting if it dropped."""
    if state.mcp is None or not state.mcp.is_connected():
        try:
            state.mcp = build_approver_client()
            await state.mcp.__aenter__()
        except Exception as exc:
            state.mcp = None
            raise ApiProblem(503, "mcp_unavailable", f"Could not start the MCP server: {exc}") from exc
    try:
        return _unwrap(await call(state.mcp, tool, args))
    except McpUnavailable as exc:
        raise ApiProblem(503, "mcp_unavailable", str(exc)) from exc


def _rebuild_runs_from_audit() -> None:
    """Recover run history after an API restart from the append-only audit trail."""
    for e in _read_audit():
        run_id, ticket_id = e.get("run_id", ""), e.get("ticket_id")
        if not run_id.startswith("run-") or ticket_id is None:
            continue
        if e.get("event") == "run_started":
            state.runs[run_id] = RunSummary(run_id=run_id, ticket_id=ticket_id, status="running", started_at=e["ts"],
                                            activity_url=f"/api/activity?run_id={run_id}&since=0")
        elif run_id in state.runs and e.get("event") == "run_finished":
            r, res = state.runs[run_id], e.get("result") or {}
            r.status, r.finished_at = "completed", e["ts"]
            try:
                r.outcome = TicketOutcome(**{"ticket_id": ticket_id, **res})
            except Exception:  # older events only logged the status and summary
                r.outcome = TicketOutcome(ticket_id=ticket_id, final_status=res.get("final_status", "could_not_complete"),
                                          summary=str(res.get("summary", "")))
        elif run_id in state.runs and e.get("event") == "error" and state.runs[run_id].status == "running":
            state.runs[run_id].status, state.runs[run_id].error = "failed", e.get("reason")
    for r in state.runs.values():  # anything still "running" was cut off by the restart
        if r.status == "running":
            r.status, r.error = "failed", "The API restarted while this run was in progress."


@asynccontextmanager
async def lifespan(app: FastAPI):
    _rebuild_runs_from_audit()
    try:
        await mcp("list_ticket_board")  # connect early so the first request is fast
    except ApiProblem:
        pass  # reported by /api/health and retried on the next request
    yield
    for task in list(state.tasks):
        task.cancel()
    if state.mcp is not None and state.mcp.is_connected():
        await state.mcp.__aexit__(None, None, None)


app = FastAPI(title="Campus Customs Multi-Agent Operations API", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(ApiProblem)
async def _api_problem(_: Request, exc: ApiProblem) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}})


@app.exception_handler(RequestValidationError)
async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "problem": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": "The request is not valid.", "details": {"errors": errors}}})


# --------------------------------------------------------------------------- #
# Helpers that turn MCP rows into dashboard shapes
# --------------------------------------------------------------------------- #


def _approval_state(status_value: str, ticket_id: int | None) -> ApprovalState:
    if status_value == "pending_approval":
        return "proposed" if ticket_id in state.running_ticket_ids() else "awaiting_approval"
    return status_value if status_value in ("approved", "executed", "rejected", "failed") else "failed"  # type: ignore[return-value]


def _payment_item(row: dict[str, Any]) -> ApprovalItem:
    kind = "vendor invoice" if row["payment_type"] == "vendor_invoice" else "rent for lease"
    return ApprovalItem(
        kind="payment", id=row["id"], ticket_id=row["ticket_id"], state=_approval_state(row["status"], row["ticket_id"]),
        description=f"Pay {row['amount']:.2f} to {row['payee']} ({kind} {row['reference_id']}) from {row['account']}",
        amount=row["amount"], requested_by=row["requested_by"], created_at=row["created_at"], decided_by=row["decided_by"],
        decided_at=row["decided_at"], decision_note=row["decision_note"], payment_id=row["payment_id"],
    )


def _purchase_item(row: dict[str, Any]) -> ApprovalItem:
    return ApprovalItem(
        kind="purchase", id=row["id"], ticket_id=row["ticket_id"], state=_approval_state(row["status"], row["ticket_id"]),
        description=f"Restock {row['quantity']} × {row['sku']} {row['size']} from vendor {row['vendor_id']} (est. {row['estimated_cost']:.2f})",
        amount=row["estimated_cost"], requested_by=row["requested_by"], created_at=row["created_at"], decided_by=row["decided_by"],
        decided_at=row["decided_at"], decision_note=row["decision_note"], vendor_on_hold=bool(row["vendor_on_hold"]),
    )


async def _all_approvals() -> list[ApprovalItem]:
    data = (await mcp("list_pending_approvals", {"include_decided": True}))["data"]
    return [_payment_item(r) for r in data["payment_requests"]] + [_purchase_item(r) for r in data["purchase_requests"]]


async def _find_approval(kind: str, request_id: int) -> ApprovalItem:
    for item in await _all_approvals():
        if item.kind == kind and item.id == request_id:
            return item
    raise ApiProblem(404, "not_found", f"No {kind} request with id {request_id}.")


def _runs_for(ticket_id: int) -> list[RunSummary]:
    return sorted((r for r in state.runs.values() if r.ticket_id == ticket_id), key=lambda r: r.started_at, reverse=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_audit() -> list[dict[str, Any]]:
    path = audit_trail_path()
    if not path.exists():
        return []
    with open(path, "rb") as fh:
        fcntl.flock(fh, fcntl.LOCK_SH)  # wait for any half-written append to finish
        try:
            raw = fh.read()
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    return json.loads(raw) if raw.strip() else []


def _describe(e: dict[str, Any]) -> str:
    """One readable line per audit event, for the activity feed."""
    who, ev, act = e.get("agent", "?"), e.get("event"), e.get("action")
    args, result = e.get("args") or {}, e.get("result") or {}
    if ev == "run_started":
        return f"Run started on ticket {e.get('ticket_id')}"
    if ev == "agent_started":
        return f"{who} started: {str(args.get('prompt', ''))[:160]}"
    if ev == "model_step":
        tools = result.get("tool_calls_requested") or []
        if "final_result" in tools:
            return f"{who} is giving its final answer"
        return f"{who} decided to call {', '.join(tools)}" if tools else f"{who} replied without calling a tool"
    if ev == "mcp_tool_call":
        if result.get("ok"):
            return f"{who} used {act} (ok)"
        return f"{who} used {act} → {((result.get('error') or {}).get('message') or 'error')[:160]}"
    if ev == "delegation":
        return f"{who} asked {args.get('colleague')}: {str(args.get('request', ''))[:200]}"
    if ev == "delegation_refused":
        return f"{who} → {args.get('colleague')} refused: {e.get('reason')}"
    if ev == "agent_finished":
        return f"{who} finished ({result.get('status')}): {str(result.get('summary', ''))[:200]}"
    if ev == "run_finished":
        return f"Run finished: {result.get('final_status')}. {str(result.get('summary', ''))[:200]}"
    if ev == "human_decision":
        return f"{who} {act}: {e.get('reason') or ''}".strip()
    if ev == "database_reset":
        return "Working database reset from the original"
    return f"{who}: {ev} {act or ''} {e.get('reason') or ''}".strip()


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@app.get("/api/health")
async def health() -> dict[str, Any]:
    """Is the API ready to run agents? (model, key, MCP, current activity)"""
    try:
        model, model_ok = model_id(), True
    except ConfigError as exc:
        model, model_ok = str(exc), False
    try:
        await mcp("list_ticket_board")
        mcp_ok = True
    except ApiProblem:
        mcp_ok = False
    return {
        "status": "ok" if (model_ok and mcp_ok) else "degraded",
        "model": model,
        "portkey_key_configured": bool(os.getenv("PORTKEY_API_KEY")),
        "mcp_connected": mcp_ok,
        "busy": state.busy,
    }


@app.get("/api/tickets", response_model=TicketList)
async def list_tickets() -> TicketList:
    """Every ticket on the board, open or resolved, with its latest run."""
    env = await mcp("list_ticket_board", {"include_resolved": True})
    tickets = [
        TicketSummary(**t, is_resolved=t["status"] == "resolved", latest_run=next(iter(_runs_for(t["id"])), None))
        for t in env["data"]["tickets"]
    ]
    return TicketList(shop_today=env["shop_today"], tickets=tickets)


@app.get("/api/tickets/{ticket_id}", response_model=TicketDetail)
async def get_ticket(ticket_id: int = PathParam(ge=1)) -> TicketDetail:
    """One ticket with its linked records, notes, drafts, approval requests and runs."""
    env = await mcp("get_ticket_details", {"ticket_id": ticket_id})
    d = env["data"]
    approvals = [a for a in await _all_approvals() if a.ticket_id == ticket_id]
    return TicketDetail(
        shop_today=env["shop_today"], ticket=d["ticket"], linked_records=d["linked_records"], notes=d["notes"],
        message_drafts=d["message_drafts"], approvals=approvals, runs=_runs_for(ticket_id),
    )


@app.post("/api/tickets/{ticket_id}/runs", response_model=StartRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_run(ticket_id: int = PathParam(ge=1)) -> StartRunResponse:
    """Start the agent team on a ticket. Returns at once; follow progress via activity_url."""
    ticket = (await mcp("get_ticket_details", {"ticket_id": ticket_id}))["data"]["ticket"]
    if ticket["status"] == "resolved":
        raise ApiProblem(409, "already_resolved", f"Ticket {ticket_id} is already resolved.")
    try:
        if state.team is None:
            state.team = Team()
    except ConfigError as exc:
        raise ApiProblem(503, "not_configured", str(exc)) from exc

    ticket_run = TicketRun(ticket_id=ticket_id, limits=state.team.limits)
    state.acquire_now(f"agent run {ticket_run.run_id} on ticket {ticket_id}")
    summary = RunSummary(
        run_id=ticket_run.run_id, ticket_id=ticket_id, status="running", started_at=_now(),
        activity_url=f"/api/activity?run_id={ticket_run.run_id}&since=0",
    )
    state.runs[summary.run_id] = summary

    async def work() -> None:
        try:
            summary.outcome = await state.team.handle_ticket(ticket_id, run=ticket_run)
            summary.status = "completed"
        except Exception as exc:  # the run failed (model, MCP or code error); record it
            summary.status, summary.error = "failed", f"{type(exc).__name__}: {exc}"
            audit.log("error", run=ticket_run, agent="boss", reason=summary.error)
        finally:
            summary.finished_at = _now()
            state.release()

    task = asyncio.create_task(work())
    state.tasks.add(task)
    task.add_done_callback(state.tasks.discard)
    return StartRunResponse(run=summary, message=f"The agent team is working on ticket {ticket_id}. Poll {summary.activity_url}.")


@app.post("/api/tickets/{ticket_id}/notes", status_code=status.HTTP_201_CREATED)
async def add_note(body: NoteRequest, ticket_id: int = PathParam(ge=1)) -> dict[str, Any]:
    """A human leaves a decision or instruction on a ticket. The Boss reads it on the next run."""
    who = body.author.strip()
    if who.lower().replace(" ", "_") in AGENT_NAMES:
        raise ApiProblem(422, "agent_cannot_write_human_note", f"{who!r} is an agent name. Notes here come from a human.")
    state.acquire_now(f"human note on ticket {ticket_id}")
    try:
        data = (await mcp("add_human_note", {"ticket_id": ticket_id, "author": who, "note": body.note.strip()}))["data"]
        audit.log_human("human_decision", ticket_id=ticket_id, actor=who, action=f"note on ticket {ticket_id}",
                        args=body.model_dump(), result=data, reason=body.note.strip())
        return {"note": data, "message": "Note saved. Send the ticket to the team again so the Boss can act on it."}
    finally:
        state.release()


@app.get("/api/runs", response_model=list[RunSummary])
async def list_runs(ticket_id: int | None = Query(default=None, ge=1)) -> list[RunSummary]:
    """Runs started since the API last started (newest first), optionally for one ticket."""
    runs = state.runs.values() if ticket_id is None else _runs_for(ticket_id)
    return sorted(runs, key=lambda r: r.started_at, reverse=True)


@app.get("/api/runs/{run_id}", response_model=RunSummary)
async def get_run(run_id: str) -> RunSummary:
    """One run's status (running, completed or failed) and, when done, the Boss's outcome."""
    if run_id not in state.runs:
        raise ApiProblem(404, "not_found", f"No run {run_id} since the API started. Its events are still in /api/activity.")
    return state.runs[run_id]


@app.get("/api/activity", response_model=ActivityPage)
async def activity(
    since: int = Query(default=0, ge=0, description="Return events after this cursor (use next_since from the last page)."),
    run_id: str | None = Query(default=None),
    ticket_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
) -> ActivityPage:
    """New audit-trail events since a cursor: what each agent did, said and which tools it used."""
    all_events = _read_audit()
    picked: list[ActivityEvent] = []
    for seq, e in enumerate(all_events[since:], start=since):
        if run_id and e.get("run_id") != run_id:
            continue
        if ticket_id and e.get("ticket_id") != ticket_id:
            continue
        picked.append(ActivityEvent(seq=seq, summary=_describe(e), **{k: e.get(k) for k in ActivityEvent.model_fields if k in e}))
        if len(picked) >= limit:
            break
    next_since = (picked[-1].seq + 1) if len(picked) >= limit else len(all_events)
    return ActivityPage(events=picked, next_since=next_since, run=state.runs.get(run_id) if run_id else None, busy=state.busy)


@app.get("/api/approvals", response_model=list[ApprovalItem])
async def list_approvals(
    state_filter: ApprovalState | None = Query(default=None, alias="state"),
    ticket_id: int | None = Query(default=None, ge=1),
) -> list[ApprovalItem]:
    """Every payment and purchase request with its lifecycle state."""
    items = await _all_approvals()
    return [i for i in items if (state_filter is None or i.state == state_filter) and (ticket_id is None or i.ticket_id == ticket_id)]


@app.post("/api/approvals/{kind}/{request_id}/decision", response_model=DecisionResponse)
async def decide(body: DecisionRequest, kind: Literal["payment", "purchase"], request_id: int = PathParam(ge=1)) -> DecisionResponse:
    """A human approves or rejects a prepared request. Approving a payment executes it now.

    The MCP server re-reads the balance inside the payment transaction and
    refuses anything that would go below zero. Then the request is 'failed' and
    no money moves.
    """
    who = body.decided_by.strip()
    if who.lower().replace(" ", "_") in AGENT_NAMES:
        raise ApiProblem(422, "agent_cannot_approve", f"{who!r} is an agent name. Decisions must be made by a human.")
    note = (body.note or "").strip()
    if body.decision == "reject" and not note:
        raise ApiProblem(422, "note_required", "Give a reason (note) when rejecting.")

    state.acquire_now(f"human decision on {kind} request {request_id}")
    try:
        item = await _find_approval(kind, request_id)
        if item.state != "awaiting_approval":
            raise ApiProblem(409, "not_awaiting_approval", f"This {kind} request is '{item.state}', so it can't be decided.", {"approval": item.model_dump()})

        payment = before = after = None
        try:
            if kind == "payment" and body.decision == "approve":
                data = (await mcp("execute_approved_payment", {"payment_request_id": request_id, "approved_by": who}))["data"]
                payment, before, after = data["payment"], data["balance_before"], data["balance_after"]
                message = f"Approved and executed: paid {payment['amount']:.2f}. Balance {before:.2f} → {after:.2f}."
            elif kind == "payment":
                await mcp("reject_payment_request", {"payment_request_id": request_id, "rejected_by": who, "reason": note})
                message = "Payment request rejected. No money moved."
            else:
                await mcp("decide_purchase_request", {"purchase_request_id": request_id, "decision": body.decision, "decided_by": who, "note": note})
                message = ("Purchase approved and recorded. No vendor was contacted and no money moved."
                           if body.decision == "approve" else "Purchase request rejected.")
        except ApiProblem as exc:
            # A refused execution (e.g. insufficient funds) is recorded as 'failed'; include the new state.
            failed = await _find_approval(kind, request_id)
            audit.log_human("human_decision", ticket_id=item.ticket_id, actor=who, action=f"{body.decision} {kind} {request_id}",
                            args=body.model_dump(), result={"error": exc.code, "state": failed.state}, reason=exc.message)
            exc.details = {**exc.details, "approval": failed.model_dump()}
            raise

        updated = await _find_approval(kind, request_id)
        audit.log_human("human_decision", ticket_id=item.ticket_id, actor=who, action=f"{body.decision} {kind} {request_id}",
                        args=body.model_dump(), result={"state": updated.state, "payment": payment}, reason=message)
        return DecisionResponse(approval=updated, executed=updated.state == "executed", message=message,
                                payment=payment, balance_before=before, balance_after=after)
    finally:
        state.release()


@app.get("/api/cash", response_model=CashResponse)
async def cash() -> CashResponse:
    """The checking balance from cash_accounts, the bills on record and the payments made."""
    env = await mcp("get_cash_position")
    d = env["data"]
    if not d["accounts"]:
        raise ApiProblem(404, "not_found", "cash_accounts has no rows.")
    main_account = next((a for a in d["accounts"] if a["account"] == "checking"), d["accounts"][0])
    return CashResponse(
        shop_today=env["shop_today"], account=main_account["account"], balance=main_account["balance"],
        balance_as_of=main_account["balance_as_of"], accounts=d["accounts"], obligations_on_record=d["obligations_on_record"],
        balance_after_all_obligations=d["balance_after_all_obligations"], payments=d["payments"],
    )


@app.post("/api/admin/reset", response_model=ResetResponse)
async def reset_database(body: ResetRequest) -> ResetResponse:
    """Replace the working copy with a fresh copy of the original. Refused while anything is running."""
    state.acquire_now("database reset")
    try:
        src, dst = ORIGINAL_DB.resolve(), WORKING_DB.resolve()
        # Guards: the original is only ever read, and only the working copy is replaced.
        if src == dst or dst.name != "campus_customs_new.db" or src.name != "campus_customs.db":
            raise ApiProblem(500, "unsafe_reset", "Refusing to reset: database paths are not the expected original and working copy.")
        if not src.is_file():
            raise ApiProblem(500, "original_missing", f"The original database {src.name} is missing; nothing to reset from.")
        original_hash = _sha256(src)
        fd, tmp_name = tempfile.mkstemp(dir=dst.parent, prefix=".reset-", suffix=".db")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            shutil.copyfile(src, tmp)
            # mkstemp creates the file owner-only; keep the working copy's usual permissions.
            os.chmod(tmp, (dst.stat().st_mode & 0o777) if dst.exists() else 0o644)
            if _sha256(tmp) != original_hash:
                raise ApiProblem(500, "copy_failed", "The fresh copy didn't match the original; the working copy was left as it was.")
            os.replace(tmp, dst)  # atomic swap; the original is untouched
        finally:
            tmp.unlink(missing_ok=True)
        for suffix in ("-journal", "-wal", "-shm"):
            Path(f"{dst}{suffix}").unlink(missing_ok=True)
        matches = _sha256(dst) == original_hash and _sha256(src) == original_hash
        audit.log_human("database_reset", ticket_id=None, actor="system", action="reset working database",
                        result={"working_copy_matches_original": matches}, reason="POST /api/admin/reset")
    finally:
        state.release()

    cash_data = (await mcp("get_cash_position"))["data"]
    board = (await mcp("list_ticket_board"))["data"]
    return ResetResponse(
        reset=True,
        message="The working database was replaced with a fresh copy of the original. The audit trail is kept (it is append-only).",
        working_copy_matches_original=matches,
        balance=cash_data["total_balance"],
        open_tickets=board["count"],
    )
