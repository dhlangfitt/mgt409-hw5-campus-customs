"""Campus Customs MCP server.

This server is the only way the agent team reads or changes the shop database.
It opens only the working copy, data/campus_customs_new.db. The original
data/campus_customs.db is never opened. If the CAMPUS_CUSTOMS_DB override points
at the original, the server refuses to use it.

Two modes:

    python mcp_server/server.py              agent mode (default)
    python mcp_server/server.py --approver   approver mode

Agent mode has the tools agents may use: read tools plus "prepare" tools that
create payment requests, purchase requests, message drafts and ticket notes.
It contains NO tool that moves money. Approver mode adds the human-approval
tools (execute or reject a payment request, decide a purchase request). Only
the human-approval process starts the server in this mode. The agents' MCP
connection always starts it in agent mode, so those tools don't exist anywhere
an agent can reach.

Every tool returns a JSON object with the same envelope:

    ok               true if the tool ran; false if it stopped
    tool             the tool's name
    shop_today       desk.date_today, the shop's definition of today (null if unusable)
    data             the tool's result (only when ok is true)
    not_in_database  things the agent might want that the database does not hold
    assumptions      rules the tool applied to the data, stated so they can be checked
    source_tables    the tables the tool read or wrote
    error            {type, message, ...} (only when ok is false); type is one of
                     invalid_input, not_found, refused, database_unavailable,
                     database_error
"""

from __future__ import annotations

import argparse
import calendar
import math
import os
import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Callable, Literal

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ORIGINAL_DB = PROJECT_ROOT / "data" / "campus_customs.db"
DEFAULT_WORKING_DB = PROJECT_ROOT / "data" / "campus_customs_new.db"


def _resolve_working_db() -> Path:
    """The working copy, or a test copy named by CAMPUS_CUSTOMS_DB (never the original)."""
    override = os.environ.get("CAMPUS_CUSTOMS_DB")
    path = Path(override).expanduser().resolve() if override else DEFAULT_WORKING_DB
    if path == ORIGINAL_DB.resolve():
        raise SystemExit("CAMPUS_CUSTOMS_DB points at the original database; refusing to use it.")
    return path


WORKING_DB = _resolve_working_db()
WORKING_DB_LABEL = (
    "data/campus_customs_new.db" if WORKING_DB == DEFAULT_WORKING_DB else f"test copy {WORKING_DB.name}"
)

# The five agents. "Prepare" tools only accept these names as the author, and the
# approval tools refuse them, so an agent's name can never stand in for a human.
AGENT_NAMES = ("boss", "inventory", "accounting", "facilities", "customer_service")

# Which agents each write tool accepts. The backend also hides tools from agents
# that shouldn't have them; this is the server-side second check.
PAYMENT_PREPARERS = ("accounting",)
PURCHASE_PREPARERS = ("inventory", "accounting")
TICKET_STATUS_SETTERS = ("boss",)

# invoices.status had no defined values in the original data; 'open' was the only
# one. This server writes 'paid' when a human-approved payment settles an invoice.
OUTSTANDING_INVOICE_STATUS = "open"
PAID_INVOICE_STATUS = "paid"

TICKET_STATUSES = ("open", "in_progress", "awaiting_approval", "resolved")
REQUEST_PENDING = "pending_approval"

UNPAID_MEANS_OPEN = (
    "An invoice counts as unpaid when invoices.status is 'open'. A human-approved "
    "payment sets it to 'paid'."
)
VENDOR_HOLD_RULE = (
    "Shop rule from the project brief: a vendor will not ship new products while it "
    "has an unpaid invoice outstanding."
)
NOT_SENT = (
    "Drafts stay on the board. Nothing is emailed or sent to customers, vendors or "
    "landlords."
)

mcp = FastMCP(
    "campus-customs",
    instructions=(
        f"Tools for the Campus Customs shop database ({WORKING_DB_LABEL}). Due dates "
        "and overdue checks use desk.date_today, the shop's today, not the real "
        "calendar. Every tool returns ok=true with data, or ok=false with an error. "
        "Anything the database does not hold is listed under not_in_database instead "
        "of being guessed. Agents can only PREPARE payment and purchase requests; "
        "money moves only after a human approves through the separate approval "
        "process. Message drafts are never sent."
    ),
)


# --------------------------------------------------------------------------- #
# Errors and the shared response envelope
# --------------------------------------------------------------------------- #


class ToolInputError(ValueError):
    """The caller passed an argument the tool cannot use."""


class RecordNotFound(LookupError):
    """The record the caller asked for is not in the database."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details


class Refused(RuntimeError):
    """A shop rule stops this action (no cash, duplicate, wrong role, ...)."""

    def __init__(self, reason: str, message: str, *, commit: bool = False, **details: Any) -> None:
        super().__init__(message)
        self.details = {"reason": reason, **details}
        # commit=True: keep what the tool recorded before refusing (e.g. marking a
        # payment request 'failed'). Nothing that moves money is ever kept.
        self.commit = commit


class DatabaseUnavailable(RuntimeError):
    """The working database file is missing or cannot be opened."""


class _Report:
    """Collects the envelope fields a tool fills in while it works."""

    def __init__(self) -> None:
        self.shop_today: date | None = None
        self.not_in_database: list[str] = []
        self.assumptions: list[str] = []

    def gap(self, message: str) -> None:
        if message not in self.not_in_database:
            self.not_in_database.append(message)

    def assume(self, message: str) -> None:
        if message not in self.assumptions:
            self.assumptions.append(message)


def _error(tool: str, kind: str, message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "tool": tool, "error": {"type": kind, "message": message, **details}}


# --------------------------------------------------------------------------- #
# Database access
# --------------------------------------------------------------------------- #

# Tables this server adds to the working copy. The original shop tables are not
# altered. Resetting the working copy removes these; they're recreated on first use.
WORKFLOW_SCHEMA = """
CREATE TABLE IF NOT EXISTS payment_requests (
    id INTEGER PRIMARY KEY,
    payment_type TEXT NOT NULL CHECK (payment_type IN ('vendor_invoice', 'rent')),
    reference_id INTEGER NOT NULL,
    ticket_id INTEGER,
    payee TEXT,
    amount REAL NOT NULL CHECK (amount > 0),
    account TEXT NOT NULL,
    due_date TEXT,
    reason TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT,
    decision_note TEXT,
    payment_id INTEGER
);
CREATE TABLE IF NOT EXISTS purchase_requests (
    id INTEGER PRIMARY KEY,
    vendor_id INTEGER NOT NULL,
    sku TEXT NOT NULL,
    size TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_cost REAL NOT NULL,
    estimated_cost REAL NOT NULL,
    ticket_id INTEGER,
    vendor_on_hold INTEGER NOT NULL,
    expected_arrival TEXT,
    reason TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT,
    decision_note TEXT
);
CREATE TABLE IF NOT EXISTS message_drafts (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    recipient_type TEXT NOT NULL CHECK (recipient_type IN ('customer', 'vendor', 'landlord')),
    recipient_name TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    author TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status = 'draft'),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_notes (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    author TEXT NOT NULL,
    status_after TEXT,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""
WORKFLOW_TABLES = ("payment_requests", "purchase_requests", "message_drafts", "ticket_notes")

_schema_ready_for: tuple[int, int] | None = None


def _ensure_workflow_schema() -> None:
    """Create the workflow tables once per database file.

    Keyed on the file's identity, so after a database reset (which swaps in a
    fresh copy of the original) the tables are created again.
    """
    global _schema_ready_for
    stat = WORKING_DB.stat()
    identity = (stat.st_dev, stat.st_ino)
    if _schema_ready_for == identity:
        return
    with closing(sqlite3.connect(f"{WORKING_DB.as_uri()}?mode=rw", uri=True, timeout=5)) as conn:
        conn.executescript(WORKFLOW_SCHEMA)
    _schema_ready_for = identity


def _connect(write: bool = False) -> sqlite3.Connection:
    """Open the working database: read-only unless the tool writes.

    Neither mode creates a missing file, so a bad path can't silently turn into
    an empty database.
    """
    if not WORKING_DB.is_file():
        raise DatabaseUnavailable(
            f"The working database {WORKING_DB_LABEL} was not found. Recreate it from "
            "the original by running, in the hw5 folder: "
            "cp data/campus_customs.db data/campus_customs_new.db"
        )
    try:
        _ensure_workflow_schema()
        mode = "rw" if write else "ro"
        # isolation_level=None: transactions are opened explicitly (BEGIN IMMEDIATE in _run).
        conn = sqlite3.connect(f"{WORKING_DB.as_uri()}?mode={mode}", uri=True, timeout=5, isolation_level=None)
    except sqlite3.Error as exc:
        raise DatabaseUnavailable(f"Could not open {WORKING_DB_LABEL}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn


def _run(
    tool: str,
    source_tables: list[str],
    work: Callable[[sqlite3.Connection, _Report], dict[str, Any]],
    *,
    write: bool = False,
) -> dict[str, Any]:
    """Open the database, run one tool's work and wrap the result or the error.

    Write tools run inside one transaction: any error rolls everything back.
    """
    report = _Report()
    try:
        with closing(_connect(write=write)) as conn:
            if write:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    data = work(conn, report)
                    conn.execute("COMMIT")
                except Refused as exc:
                    conn.execute("COMMIT" if exc.commit else "ROLLBACK")
                    raise
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
            else:
                data = work(conn, report)
    except ToolInputError as exc:
        return _error(tool, "invalid_input", str(exc))
    except RecordNotFound as exc:
        return _error(tool, "not_found", str(exc), **exc.details)
    except Refused as exc:
        return _error(tool, "refused", str(exc), **exc.details)
    except DatabaseUnavailable as exc:
        return _error(tool, "database_unavailable", str(exc))
    except sqlite3.Error as exc:
        return _error(tool, "database_error", f"{type(exc).__name__}: {exc}")
    return {
        "ok": True,
        "tool": tool,
        "shop_today": report.shop_today.isoformat() if report.shop_today else None,
        "data": data,
        "not_in_database": report.not_in_database,
        "assumptions": report.assumptions,
        "source_tables": source_tables,
    }


# --------------------------------------------------------------------------- #
# Input checks (FastMCP also validates against the parameter schemas; these
# checks cover direct calls and values the schema cannot rule out)
# --------------------------------------------------------------------------- #


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolInputError(f"{name} must be a whole number; got {value!r}.")
    if value < 1:
        raise ToolInputError(f"{name} must be 1 or more; got {value}.")
    return value


def _text(name: str, value: Any, max_length: int = 40) -> str:
    if not isinstance(value, str):
        raise ToolInputError(f"{name} must be text; got {value!r}.")
    cleaned = value.strip()
    if not cleaned:
        raise ToolInputError(f"{name} must not be empty.")
    if len(cleaned) > max_length:
        raise ToolInputError(f"{name} must be at most {max_length} characters.")
    return cleaned


def _percent(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolInputError(f"{name} must be a number; got {value!r}.")
    number = float(value)
    if not math.isfinite(number) or number < 0 or number >= 100:
        raise ToolInputError(f"{name} must be at least 0 and less than 100; got {value!r}.")
    return number


def _amount(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolInputError(f"{name} must be a number; got {value!r}.")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ToolInputError(f"{name} must be more than 0; got {value!r}.")
    return number


def _choice(name: str, value: Any, allowed: tuple[str, ...]) -> str:
    cleaned = _text(name, value).lower()
    if cleaned not in allowed:
        raise ToolInputError(f"{name} must be one of {', '.join(allowed)}; got {value!r}.")
    return cleaned


def _agent(name: str, value: Any, allowed: tuple[str, ...]) -> str:
    """The acting agent, which must be one of the agents allowed to use this tool."""
    who = _text(name, value).lower()
    if who not in AGENT_NAMES:
        raise ToolInputError(f"{name} must be one of the agents ({', '.join(AGENT_NAMES)}); got {value!r}.")
    if who not in allowed:
        raise Refused("role_not_allowed", f"The {who} agent may not use this tool. Allowed: {', '.join(allowed)}.")
    return who


def _human(name: str, value: Any) -> str:
    """A human approver's name. Agent names are refused."""
    who = _text(name, value, max_length=80)
    if who.lower() in AGENT_NAMES or who.lower().replace(" ", "_") in AGENT_NAMES:
        raise Refused("agent_cannot_approve", f"{name} must be a human; {who!r} is an agent name.")
    return who


# --------------------------------------------------------------------------- #
# Shared lookups
# --------------------------------------------------------------------------- #


def _money(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_date(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def _add_one_month(day: date) -> date:
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _load_shop_today(conn: sqlite3.Connection, report: _Report) -> date | None:
    rows = conn.execute("SELECT date_today FROM desk").fetchall()
    if len(rows) != 1:
        report.gap(
            "The shop's today (desk.date_today) is not available: desk has "
            f"{len(rows)} rows instead of exactly one, so date-based fields are null."
        )
        return None
    raw = rows[0]["date_today"]
    today = _parse_date(raw)
    if today is None:
        report.gap(
            f"desk.date_today is {raw!r}, which is not a YYYY-MM-DD date, so "
            "date-based fields are null."
        )
    report.shop_today = today
    return today


def _due_status(raw_due: Any, today: date | None, label: str, report: _Report) -> dict[str, Any]:
    """Where a due date sits relative to the shop's today."""
    status: dict[str, Any] = {
        "due_date": raw_due,
        "is_overdue": None,
        "days_overdue": None,
        "days_until_due": None,
    }
    due = _parse_date(raw_due)
    if due is None:
        report.gap(f"{label} is {raw_due!r}, not a YYYY-MM-DD date, so its due status is unknown.")
        return status
    if today is None:
        return status
    delta = (due - today).days
    status.update(is_overdue=delta < 0, days_overdue=max(0, -delta), days_until_due=max(0, delta))
    return status


def _existing(conn: sqlite3.Connection, sql: str, limit: int = 25) -> list[Any]:
    return [row[0] for row in conn.execute(f"{sql} LIMIT ?", (limit,))]


def _require_ticket(conn: sqlite3.Connection, ticket_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise RecordNotFound(
            f"No ticket with id {ticket_id} in the tickets table.",
            existing_ticket_ids=_existing(conn, "SELECT id FROM tickets ORDER BY id"),
        )
    return row


def _pick_account(conn: sqlite3.Connection, account: str | None) -> sqlite3.Row:
    rows = conn.execute("SELECT name, balance, date FROM cash_accounts ORDER BY name").fetchall()
    if account:
        match = next((r for r in rows if r["name"].lower() == account.lower()), None)
        if match is None:
            raise RecordNotFound(f"No cash account named {account!r}.", existing_accounts=[r["name"] for r in rows])
        return match
    if len(rows) == 1:
        return rows[0]
    if not rows:
        raise Refused("no_cash_account", "cash_accounts has no rows, so there is nothing to pay from.")
    raise ToolInputError(
        "There is more than one cash account; name one in account.",
    )


def _vendor_hold(conn: sqlite3.Connection, vendor_id: int, today: date | None, report: _Report) -> dict[str, Any]:
    unpaid_rows = conn.execute(
        "SELECT id, amount, due_date, description FROM invoices "
        "WHERE vendor_id = ? AND status = ? ORDER BY due_date, id",
        (vendor_id, OUTSTANDING_INVOICE_STATUS),
    ).fetchall()
    unpaid = [
        {
            "id": r["id"],
            "amount": _money(r["amount"]),
            "description": r["description"],
            **_due_status(r["due_date"], today, f"invoices.due_date for invoice {r['id']}", report),
        }
        for r in unpaid_rows
    ]
    report.assume(UNPAID_MEANS_OPEN)
    report.assume(VENDOR_HOLD_RULE)
    return {
        "vendor_will_ship_new_products": not unpaid,
        "blocking_invoice_ids": [item["id"] for item in unpaid],
        "unpaid_invoices": unpaid,
        "unpaid_total": _money(sum(item["amount"] or 0 for item in unpaid)),
    }


def _earliest_arrival(today: date | None, lead_days: Any, report: _Report) -> str | None:
    report.assume(
        "earliest_arrival_if_shipped_on_shop_today = shop_today + vendors.lead_days. "
        "A vendor on hold will not ship, so the date is only reachable once the hold is cleared."
    )
    if today is None or lead_days is None:
        return None
    return (today + timedelta(days=int(lead_days))).isoformat()


def _cash_position(
    conn: sqlite3.Connection,
    report: _Report,
    today: date | None,
    amount: float,
    *,
    this_invoice_id: int | None = None,
    this_lease_id: int | None = None,
) -> dict[str, Any]:
    """Cash on hand against one amount, alongside everything else owed on record."""
    accounts = conn.execute(
        "SELECT name, balance, date FROM cash_accounts ORDER BY name"
    ).fetchall()
    if not accounts:
        report.gap("cash_accounts has no rows, so the cash available to pay with is not in the database.")

    account_list = []
    for row in accounts:
        balance = float(row["balance"])
        covers = balance >= amount
        account_list.append(
            {
                "account": row["name"],
                "balance": _money(balance),
                "balance_as_of": row["date"],
                "covers_this_amount": covers,
                "balance_after_this_amount": _money(balance - amount) if covers else None,
            }
        )
    total_balance = sum(float(row["balance"]) for row in accounts) if accounts else None

    others: list[dict[str, Any]] = []
    invoice_rows = conn.execute(
        """
        SELECT i.id, i.amount, i.due_date, i.description, i.vendor_id, v.name AS vendor_name
        FROM invoices AS i
        LEFT JOIN vendors AS v ON v.id = i.vendor_id
        WHERE i.status = ?
        ORDER BY i.due_date, i.id
        """,
        (OUTSTANDING_INVOICE_STATUS,),
    ).fetchall()
    for row in invoice_rows:
        if row["id"] == this_invoice_id:
            continue
        if row["vendor_name"] is None:
            report.gap(f"Invoice {row['id']} names vendor_id {row['vendor_id']}, which is not in vendors.")
        others.append(
            {
                "source_table": "invoices",
                "id": row["id"],
                "payee": row["vendor_name"],
                "amount": _money(row["amount"]),
                "description": row["description"],
                **_due_status(row["due_date"], today, f"invoices.due_date for invoice {row['id']}", report),
            }
        )
    lease_rows = conn.execute(
        "SELECT id, space_name, landlord, monthly_rent, next_due FROM leases ORDER BY next_due, id"
    ).fetchall()
    for row in lease_rows:
        if row["id"] == this_lease_id:
            continue
        others.append(
            {
                "source_table": "leases",
                "id": row["id"],
                "payee": row["landlord"],
                "amount": _money(row["monthly_rent"]),
                "description": f"Monthly rent, {row['space_name']}",
                **_due_status(row["next_due"], today, f"leases.next_due for lease {row['id']}", report),
            }
        )
    others_total = sum(item["amount"] or 0 for item in others)

    report.assume(UNPAID_MEANS_OPEN)
    report.assume(
        "Other obligations on record = every invoice with status 'open' plus each "
        "lease's next rent payment. The database holds nothing else the shop owes."
    )
    report.assume("Cash figures here are read-only checks. Checking cash does not make or approve a payment.")
    return {
        "amount_checked": _money(amount),
        "accounts": account_list,
        "total_balance": _money(total_balance),
        "other_obligations_on_record": others,
        "other_obligations_total": _money(others_total),
        "total_balance_after_this_and_all_other_obligations": (
            _money(total_balance - amount - others_total) if total_balance is not None else None
        ),
    }


def _tickets(conn: sqlite3.Connection, where: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT id, type, requester, subject, sku, size, qty, status FROM tickets WHERE {where} ORDER BY id",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _note(conn: sqlite3.Connection, ticket_id: int | None, author: str, note: str, status_after: str | None = None) -> None:
    if ticket_id is None:
        return
    conn.execute(
        "INSERT INTO ticket_notes (ticket_id, author, status_after, note, created_at) VALUES (?, ?, ?, ?, ?)",
        (ticket_id, author, status_after, note, _now()),
    )


# =========================================================================== #
# AGENT-MODE TOOLS: reading
# =========================================================================== #


def list_ticket_board(
    include_resolved: Annotated[bool, Field(description="Also list resolved tickets.")] = False,
) -> dict[str, Any]:
    """List the tickets on the shop's open-ticket board.

    Returns each ticket's id, type, requester, subject, status and created time,
    with counts of the pending approval requests and message drafts attached to
    it. Resolved tickets are left out unless include_resolved is true.
    """
    tool = "list_ticket_board"
    if not isinstance(include_resolved, bool):
        return _error(tool, "invalid_input", "include_resolved must be true or false.")

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        _load_shop_today(conn, report)
        where = "" if include_resolved else "WHERE t.status != 'resolved'"
        tickets = _rows(
            conn,
            f"""
            SELECT t.id, t.type, t.requester, t.subject, t.status, t.created_at,
                   (SELECT COUNT(*) FROM payment_requests p WHERE p.ticket_id = t.id AND p.status = ?) +
                   (SELECT COUNT(*) FROM purchase_requests q WHERE q.ticket_id = t.id AND q.status = ?)
                       AS pending_approval_requests,
                   (SELECT COUNT(*) FROM message_drafts d WHERE d.ticket_id = t.id) AS message_drafts
            FROM tickets AS t {where} ORDER BY t.id
            """,
            (REQUEST_PENDING, REQUEST_PENDING),
        )
        return {"tickets": tickets, "count": len(tickets)}

    return _run(tool, ["tickets", "payment_requests", "purchase_requests", "message_drafts", "desk"], work)


def get_ticket_details(
    ticket_id: Annotated[int, Field(ge=1, description="The ticket id from the board.")],
) -> dict[str, Any]:
    """Read one ticket in full, with the records it points at and the work done on it so far.

    Returns the ticket, a short summary of each linked record (the invoice it
    names, the lease it names, the stock row for its SKU and size), and the notes,
    message drafts, payment requests and purchase requests already attached to it.
    Use the specialist tools for the detailed analysis of each linked record.
    """
    tool = "get_ticket_details"
    try:
        ticket_id = _positive_int("ticket_id", ticket_id)
    except ToolInputError as exc:
        return _error(tool, "invalid_input", str(exc))

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        _load_shop_today(conn, report)
        ticket = dict(_require_ticket(conn, ticket_id))
        linked: dict[str, Any] = {}
        if ticket["invoice_id"] is not None:
            row = conn.execute(
                "SELECT i.id, i.amount, i.due_date, i.status, v.id AS vendor_id, v.name AS vendor "
                "FROM invoices i LEFT JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?",
                (ticket["invoice_id"],),
            ).fetchone()
            linked["invoice"] = dict(row) if row else None
            if row is None:
                report.gap(f"Ticket {ticket_id} names invoice {ticket['invoice_id']}, which is not in invoices.")
        if ticket["lease_id"] is not None:
            row = conn.execute(
                "SELECT id, space_name, landlord, monthly_rent, next_due FROM leases WHERE id = ?",
                (ticket["lease_id"],),
            ).fetchone()
            linked["lease"] = dict(row) if row else None
            if row is None:
                report.gap(f"Ticket {ticket_id} names lease {ticket['lease_id']}, which is not in leases.")
        if ticket["sku"]:
            row = conn.execute(
                "SELECT sku, name, size, qty AS on_hand, location FROM inventory "
                "WHERE upper(sku) = upper(?) AND upper(size) = upper(?)",
                (ticket["sku"], ticket["size"] or ""),
            ).fetchone()
            linked["stock"] = dict(row) if row else None
            if row is None:
                report.gap(f"No inventory row for ticket {ticket_id}'s SKU {ticket['sku']} size {ticket['size']}.")
        return {
            "ticket": ticket,
            "linked_records": linked,
            "notes": _rows(conn, "SELECT author, status_after, note, created_at FROM ticket_notes WHERE ticket_id = ? ORDER BY id", (ticket_id,)),
            "message_drafts": _rows(conn, "SELECT id, recipient_type, recipient_name, subject, author, status, created_at FROM message_drafts WHERE ticket_id = ? ORDER BY id", (ticket_id,)),
            "payment_requests": _rows(conn, "SELECT id, payment_type, reference_id, amount, payee, status, requested_by FROM payment_requests WHERE ticket_id = ? ORDER BY id", (ticket_id,)),
            "purchase_requests": _rows(conn, "SELECT id, vendor_id, sku, size, quantity, estimated_cost, vendor_on_hold, status, requested_by FROM purchase_requests WHERE ticket_id = ? ORDER BY id", (ticket_id,)),
        }

    return _run(
        tool,
        ["tickets", "invoices", "vendors", "leases", "inventory", "ticket_notes", "message_drafts", "payment_requests", "purchase_requests", "desk"],
        work,
    )


INVOICE_SOURCES = ["invoices", "vendors", "tickets", "desk", "cash_accounts", "leases"]


def get_invoice_and_vendor_status(
    invoice_id: Annotated[int, Field(ge=1, description="The invoice id, e.g. from a ticket's invoice_id field.")],
) -> dict[str, Any]:
    """Look up one vendor invoice and everything needed to decide whether to pay it.

    Returns the invoice (amount, status, and whether it is overdue against the
    shop's today), the vendor who sent it (specialty and lead time), every unpaid
    invoice that vendor still has, and whether the vendor is on a shipping hold
    under the shop rule that vendors will not ship new products while any of
    their invoices is unpaid. Also returns the tickets that point at this invoice
    and, for an unpaid invoice, the cash position: whether each cash account
    covers it and what would be left after every other bill on record.
    Read-only. It does not pay anything.
    """
    tool = "get_invoice_and_vendor_status"
    try:
        invoice_id = _positive_int("invoice_id", invoice_id)
    except ToolInputError as exc:
        return _error(tool, "invalid_input", str(exc))

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        today = _load_shop_today(conn, report)
        row = conn.execute(
            "SELECT id, vendor_id, amount, due_date, status, description FROM invoices WHERE id = ?",
            (invoice_id,),
        ).fetchone()
        if row is None:
            raise RecordNotFound(
                f"No invoice with id {invoice_id} in the invoices table.",
                existing_invoice_ids=_existing(conn, "SELECT id FROM invoices ORDER BY id"),
            )

        report.assume(UNPAID_MEANS_OPEN)
        is_unpaid = row["status"] == OUTSTANDING_INVOICE_STATUS
        if is_unpaid:
            due = _due_status(row["due_date"], today, f"invoices.due_date for invoice {invoice_id}", report)
        else:
            due = {"due_date": row["due_date"], "is_overdue": False, "days_overdue": 0, "days_until_due": None}
        invoice = {
            "id": row["id"],
            "vendor_id": row["vendor_id"],
            "amount": _money(row["amount"]),
            "status": row["status"],
            "is_unpaid": is_unpaid,
            "description": row["description"],
            **due,
        }

        vendor = shipping_hold = lead_time = None
        vendor_row = conn.execute(
            "SELECT id, name, specialty, lead_days FROM vendors WHERE id = ?", (row["vendor_id"],)
        ).fetchone()
        if vendor_row is None:
            report.gap(
                f"Invoice {invoice_id} names vendor_id {row['vendor_id']}, but no vendor has "
                "that id, so the vendor, its lead time and its shipping hold are unknown."
            )
        else:
            vendor = dict(vendor_row)
            shipping_hold = _vendor_hold(conn, vendor_row["id"], today, report)
            lead_time = {
                "lead_days": vendor_row["lead_days"],
                "earliest_arrival_if_shipped_on_shop_today": _earliest_arrival(today, vendor_row["lead_days"], report),
            }
            report.gap(
                "Which products this vendor supplies is not recorded: there is no "
                "product-to-vendor link. invoices.description is free text and is not parsed."
            )

        cash = None
        if is_unpaid:
            cash = _cash_position(conn, report, today, float(row["amount"]), this_invoice_id=invoice_id)
        else:
            report.assume("Cash position is only calculated for unpaid invoices.")

        return {
            "invoice": invoice,
            "vendor": vendor,
            "vendor_shipping_hold": shipping_hold,
            "lead_time": lead_time,
            "tickets_linked_to_this_invoice": _tickets(conn, "invoice_id = ?", (invoice_id,)),
            "cash_position": cash,
        }

    return _run(tool, INVOICE_SOURCES, work)


RENT_SOURCES = ["leases", "desk", "cash_accounts", "invoices", "vendors", "tickets", "payments"]


def get_rent_payment_status(
    lease_id: Annotated[int, Field(ge=1, description="The lease id, e.g. from a ticket's lease_id field.")],
) -> dict[str, Any]:
    """Look up one lease's next rent payment and whether the shop can cover it.

    Returns the lease (space, landlord, monthly rent, next due date), how many days
    until the rent is due or how many days overdue it is against the shop's today,
    the tickets that point at this lease, the rent payments already recorded for
    it, and the cash position: whether each cash account covers the rent and what
    would be left after also paying every unpaid vendor invoice and other lease on
    record. Read-only. It does not pay anything.
    """
    tool = "get_rent_payment_status"
    try:
        lease_id = _positive_int("lease_id", lease_id)
    except ToolInputError as exc:
        return _error(tool, "invalid_input", str(exc))

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        today = _load_shop_today(conn, report)
        row = conn.execute(
            "SELECT id, space_name, landlord, monthly_rent, next_due, notes FROM leases WHERE id = ?",
            (lease_id,),
        ).fetchone()
        if row is None:
            raise RecordNotFound(
                f"No lease with id {lease_id} in the leases table.",
                existing_lease_ids=_existing(conn, "SELECT id FROM leases ORDER BY id"),
            )

        # This server records rent payments with kind 'rent' and ref_id = lease id.
        rent_payments = _rows(
            conn,
            "SELECT id, amount, account, paid_at, approved_by FROM payments WHERE kind = 'rent' AND ref_id = ? ORDER BY id",
            (lease_id,),
        )
        report.assume("Rent payments are payments rows with kind 'rent' and ref_id = the lease id (written by this server's approval tool).")
        if not rent_payments:
            report.gap("No rent payment is recorded for this lease in payments.")

        return {
            "lease": dict(row),
            "rent_due": {
                "amount": _money(row["monthly_rent"]),
                **_due_status(row["next_due"], today, f"leases.next_due for lease {lease_id}", report),
            },
            "rent_payments_recorded": rent_payments,
            "tickets_linked_to_this_lease": _tickets(conn, "lease_id = ?", (lease_id,)),
            "cash_position": _cash_position(
                conn, report, today, float(row["monthly_rent"]), this_lease_id=lease_id
            ),
        }

    return _run(tool, RENT_SOURCES, work)


QUOTE_SOURCES = ["inventory", "pricing", "tickets", "desk"]


def get_stock_and_price_quote(
    sku: Annotated[str, Field(min_length=1, max_length=40, description="Product SKU as written on the ticket or in inventory. Not case-sensitive.")],
    size: Annotated[str, Field(min_length=1, max_length=40, description="Size as written on the ticket or in inventory. Not case-sensitive.")],
    quantity: Annotated[int, Field(ge=1, description="How many units the customer wants.")],
    discount_percent: Annotated[float, Field(ge=0, lt=100, description="Discount off list price to price the order at. 0 means list price.")] = 0.0,
) -> dict[str, Any]:
    """Check stock for one product and size, and price an order of it.

    Returns how many of the requested size are on hand and where, whether the
    order can be filled from stock and the shortfall if not, stock in every other
    size of the same product, the product's unit cost and list price, the
    break-even price and the largest discount that stays at or above cost, and a
    quote for the requested quantity at the given discount (total price, total
    cost, gross margin, whether it sells below cost, and the cost of the
    shortfall at unit cost). Also returns every ticket that mentions this SKU.
    Read-only. It does not reserve stock, order anything or record a sale.
    """
    tool = "get_stock_and_price_quote"
    try:
        sku = _text("sku", sku)
        size = _text("size", size)
        quantity = _positive_int("quantity", quantity)
        discount_percent = _percent("discount_percent", discount_percent)
    except ToolInputError as exc:
        return _error(tool, "invalid_input", str(exc))

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        _load_shop_today(conn, report)
        rows = conn.execute(
            "SELECT sku, name, size, qty, location FROM inventory WHERE upper(sku) = upper(?) ORDER BY rowid",
            (sku,),
        ).fetchall()
        if not rows:
            raise RecordNotFound(
                f"No inventory rows for SKU {sku!r}.",
                known_skus=_existing(conn, "SELECT DISTINCT sku FROM inventory ORDER BY sku"),
            )
        canonical_sku = rows[0]["sku"]
        match = next((r for r in rows if str(r["size"]).upper() == size.upper()), None)
        if match is None:
            raise RecordNotFound(
                f"SKU {canonical_sku} has no inventory row for size {size!r}.",
                available_sizes=[r["size"] for r in rows],
            )

        on_hand = int(match["qty"])
        shortfall = max(0, quantity - on_hand)
        stock = {
            "size": match["size"],
            "on_hand": on_hand,
            "location": match["location"],
            "quantity_requested": quantity,
            "can_fill_from_stock": shortfall == 0,
            "shortfall": shortfall,
            "all_sizes": [
                {"size": r["size"], "on_hand": int(r["qty"]), "location": r["location"]} for r in rows
            ],
            "total_on_hand_all_sizes": sum(int(r["qty"]) for r in rows),
        }

        pricing = quote = None
        price_row = conn.execute(
            "SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (canonical_sku,)
        ).fetchone()
        if price_row is None:
            report.gap(f"pricing has no row for {canonical_sku}, so costs, prices and the quote are null.")
        else:
            unit_cost = float(price_row["unit_cost"])
            list_price = float(price_row["list_price"])
            max_discount = None
            if list_price > 0:
                # Rounded down so applying it never prices below cost.
                max_discount = math.floor((list_price - unit_cost) / list_price * 1000) / 10
            pricing = {
                "unit_cost": _money(unit_cost),
                "list_price": _money(list_price),
                "unit_margin_at_list": _money(list_price - unit_cost),
                "break_even_unit_price": _money(unit_cost),
                "max_discount_percent_without_selling_below_cost": max_discount,
            }
            unit_price = list_price * (1 - discount_percent / 100)
            quote = {
                "quantity": quantity,
                "discount_percent": discount_percent,
                "unit_price": _money(unit_price),
                "total_price": _money(unit_price * quantity),
                "total_cost": _money(unit_cost * quantity),
                "gross_margin": _money((unit_price - unit_cost) * quantity),
                "below_cost": unit_price < unit_cost,
                "shortfall_cost_at_unit_cost": _money(shortfall * unit_cost),
            }
            report.assume(
                "pricing.unit_cost is treated as what the shop pays per unit, so it is the "
                "break-even price and the cost of restocking the shortfall. The database "
                "has no separate vendor price list."
            )
            report.assume(
                "The quote is arithmetic for a pricing decision only. It writes nothing, "
                "and incoming revenue is not modelled in this project."
            )

        report.gap(
            "Which vendor supplies this SKU is not recorded (no product-to-vendor link), "
            "so restock lead time and vendor holds cannot be looked up from the SKU."
        )
        report.gap("No discount policy or discount approval limit is recorded.")

        return {
            "product": {"sku": canonical_sku, "name": match["name"]},
            "stock": stock,
            "pricing": pricing,
            "quote": quote,
            "tickets_for_this_sku": _tickets(conn, "upper(sku) = upper(?)", (canonical_sku,)),
        }

    return _run(tool, QUOTE_SOURCES, work)


def list_vendors_with_status() -> dict[str, Any]:
    """List every vendor with its lead time and whether it will ship new products.

    For each vendor: name, specialty, lead_days, its unpaid invoices, whether it
    is on a shipping hold (vendors won't ship while they have an unpaid invoice),
    and the earliest arrival if it shipped on the shop's today. The database does
    not record which products each vendor supplies; pick a vendor by specialty and
    say that the choice is an inference.
    """
    tool = "list_vendors_with_status"

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        today = _load_shop_today(conn, report)
        vendors = []
        for row in conn.execute("SELECT id, name, specialty, lead_days FROM vendors ORDER BY id").fetchall():
            hold = _vendor_hold(conn, row["id"], today, report)
            vendors.append(
                {
                    **dict(row),
                    "vendor_will_ship_new_products": hold["vendor_will_ship_new_products"],
                    "blocking_invoice_ids": hold["blocking_invoice_ids"],
                    "unpaid_total": hold["unpaid_total"],
                    "earliest_arrival_if_shipped_on_shop_today": _earliest_arrival(today, row["lead_days"], report),
                }
            )
        report.gap("Which products each vendor supplies is not recorded (no product-to-vendor link).")
        return {"vendors": vendors}

    return _run(tool, ["vendors", "invoices", "desk"], work)


def check_cash_for_amount(
    amount: Annotated[float, Field(gt=0, description="The amount the shop would pay out.")],
) -> dict[str, Any]:
    """Check whether the shop's cash covers an amount, alongside every bill on record.

    Use this for amounts that aren't an existing invoice or rent, such as the
    estimated cost of a restock. Returns each account's balance and whether it
    covers the amount, every other obligation on record, and what would be left
    if the amount and all of them were paid. Read-only.
    """
    tool = "check_cash_for_amount"
    try:
        amount = _amount("amount", amount)
    except ToolInputError as exc:
        return _error(tool, "invalid_input", str(exc))

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        today = _load_shop_today(conn, report)
        return {"cash_position": _cash_position(conn, report, today, amount)}

    return _run(tool, ["cash_accounts", "invoices", "vendors", "leases", "desk"], work)


def get_cash_position() -> dict[str, Any]:
    """The shop's cash: each account's balance, every bill on record, and payments made.

    Returns the balances in cash_accounts, the unpaid invoices and next rent
    payments on record with what would be left if all were paid, and the most
    recent rows in payments with who approved them. Read-only.
    """
    tool = "get_cash_position"

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        today = _load_shop_today(conn, report)
        position = _cash_position(conn, report, today, 0.0)
        return {
            "accounts": [{k: a[k] for k in ("account", "balance", "balance_as_of")} for a in position["accounts"]],
            "total_balance": position["total_balance"],
            "obligations_on_record": position["other_obligations_on_record"],
            "obligations_total": position["other_obligations_total"],
            "balance_after_all_obligations": position["total_balance_after_this_and_all_other_obligations"],
            "payments": _rows(conn, "SELECT id, kind, ref_id, amount, account, paid_at, approved_by FROM payments ORDER BY id DESC LIMIT 20"),
        }

    return _run(tool, ["cash_accounts", "invoices", "vendors", "leases", "payments", "desk"], work)


def list_pending_approvals(
    include_decided: Annotated[bool, Field(description="Also list executed, approved, rejected and failed requests.")] = False,
) -> dict[str, Any]:
    """List payment and purchase requests waiting for a human decision (or all of them)."""
    tool = "list_pending_approvals"
    if not isinstance(include_decided, bool):
        return _error(tool, "invalid_input", "include_decided must be true or false.")

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        _load_shop_today(conn, report)
        where, params = ("", ()) if include_decided else ("WHERE status = ?", (REQUEST_PENDING,))
        return {
            "payment_requests": _rows(conn, f"SELECT * FROM payment_requests {where} ORDER BY id", params),
            "purchase_requests": _rows(conn, f"SELECT * FROM purchase_requests {where} ORDER BY id", params),
        }

    return _run(tool, ["payment_requests", "purchase_requests", "desk"], work)


# =========================================================================== #
# AGENT-MODE TOOLS: preparing (writes, but never moves money or contacts anyone)
# =========================================================================== #


def prepare_payment_request(
    payment_type: Annotated[Literal["vendor_invoice", "rent"], Field(description="'vendor_invoice' to pay an invoice, 'rent' to pay a lease's next rent.")],
    reference_id: Annotated[int, Field(ge=1, description="The invoice id (vendor_invoice) or lease id (rent).")],
    ticket_id: Annotated[int, Field(ge=1, description="The ticket this payment resolves.")],
    reason: Annotated[str, Field(min_length=1, max_length=500, description="Why this should be paid now, for the human approver.")],
    requested_by: Annotated[str, Field(description="The agent preparing the request. Only accounting may.")],
    account: Annotated[str | None, Field(description="Cash account to pay from. Leave empty if the shop has only one.")] = None,
) -> dict[str, Any]:
    """Prepare a payment request for a human to approve. This does NOT pay anything.

    The amount and payee are taken from the database (the invoice amount or the
    lease's monthly rent), not from the caller. Refuses if the invoice is
    already paid or a request for the same invoice or rent is already pending.
    Reports whether the account currently covers the amount. The payment only
    happens if a human approves it in the separate approval process, which
    refuses any payment that would take the account below zero.
    """
    tool = "prepare_payment_request"
    try:
        payment_type = _choice("payment_type", payment_type, ("vendor_invoice", "rent"))
        reference_id = _positive_int("reference_id", reference_id)
        ticket_id = _positive_int("ticket_id", ticket_id)
        reason = _text("reason", reason, max_length=500)
        account = _text("account", account) if account not in (None, "") else None
    except ToolInputError as exc:
        return _error(tool, "invalid_input", str(exc))

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        who = _agent("requested_by", requested_by, PAYMENT_PREPARERS)
        today = _load_shop_today(conn, report)
        _require_ticket(conn, ticket_id)

        if payment_type == "vendor_invoice":
            row = conn.execute(
                "SELECT i.id, i.amount, i.due_date, i.status, v.name AS vendor FROM invoices i "
                "LEFT JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?",
                (reference_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"No invoice with id {reference_id}.", existing_invoice_ids=_existing(conn, "SELECT id FROM invoices ORDER BY id"))
            if row["status"] != OUTSTANDING_INVOICE_STATUS:
                raise Refused("not_unpaid", f"Invoice {reference_id} has status {row['status']!r}, so there is nothing to pay.")
            amount, payee, due = float(row["amount"]), row["vendor"], row["due_date"]
            cash = _cash_position(conn, report, today, amount, this_invoice_id=reference_id)
        else:
            row = conn.execute("SELECT id, landlord, monthly_rent, next_due FROM leases WHERE id = ?", (reference_id,)).fetchone()
            if row is None:
                raise RecordNotFound(f"No lease with id {reference_id}.", existing_lease_ids=_existing(conn, "SELECT id FROM leases ORDER BY id"))
            amount, payee, due = float(row["monthly_rent"]), row["landlord"], row["next_due"]
            cash = _cash_position(conn, report, today, amount, this_lease_id=reference_id)

        existing = conn.execute(
            "SELECT id FROM payment_requests WHERE payment_type = ? AND reference_id = ? AND status = ?",
            (payment_type, reference_id, REQUEST_PENDING),
        ).fetchone()
        if existing:
            raise Refused("duplicate", f"Payment request {existing['id']} for this {payment_type} is already waiting for approval.", existing_request_id=existing["id"])

        acct = _pick_account(conn, account)
        covers = float(acct["balance"]) >= amount
        cur = conn.execute(
            "INSERT INTO payment_requests (payment_type, reference_id, ticket_id, payee, amount, account, due_date, reason, requested_by, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (payment_type, reference_id, ticket_id, payee, amount, acct["name"], due, reason, who, REQUEST_PENDING, _now()),
        )
        _note(conn, ticket_id, who, f"Prepared payment request {cur.lastrowid}: {payment_type} {reference_id}, {amount:.2f} to {payee}. Waiting for human approval.")
        report.assume("Preparing a request moves no money. Only a human, through the approval process, can execute it.")
        return {
            "payment_request": {
                "id": cur.lastrowid,
                "status": REQUEST_PENDING,
                "payment_type": payment_type,
                "reference_id": reference_id,
                "ticket_id": ticket_id,
                "payee": payee,
                "amount": _money(amount),
                "due_date": due,
                "account": acct["name"],
                "requested_by": who,
            },
            "account_covers_amount_now": covers,
            "cash_position": cash,
            "next_step": "A human must approve this in the approval process. Agents cannot execute payments.",
        }

    return _run(tool, ["payment_requests", "invoices", "vendors", "leases", "cash_accounts", "tickets", "ticket_notes", "desk"], work, write=True)


def prepare_purchase_request(
    vendor_id: Annotated[int, Field(ge=1, description="The vendor to buy from.")],
    sku: Annotated[str, Field(min_length=1, max_length=40, description="Product SKU.")],
    size: Annotated[str, Field(min_length=1, max_length=40, description="Size to restock.")],
    quantity: Annotated[int, Field(ge=1, description="Units to order.")],
    ticket_id: Annotated[int, Field(ge=1, description="The ticket this restock is for.")],
    reason: Annotated[str, Field(min_length=1, max_length=500, description="Why to order, for the human approver.")],
    requested_by: Annotated[str, Field(description="The agent preparing the request: inventory or accounting.")],
) -> dict[str, Any]:
    """Prepare a restock purchase request for a human to decide. This orders nothing.

    Records the vendor, product, quantity, estimated cost (quantity x
    pricing.unit_cost), whether the vendor is on a shipping hold because of an
    unpaid invoice, and the expected arrival (shop today + lead_days, only if
    the vendor is not on hold). No vendor is contacted and no money moves.
    """
    tool = "prepare_purchase_request"
    try:
        vendor_id = _positive_int("vendor_id", vendor_id)
        sku = _text("sku", sku)
        size = _text("size", size)
        quantity = _positive_int("quantity", quantity)
        ticket_id = _positive_int("ticket_id", ticket_id)
        reason = _text("reason", reason, max_length=500)
    except ToolInputError as exc:
        return _error(tool, "invalid_input", str(exc))

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        who = _agent("requested_by", requested_by, PURCHASE_PREPARERS)
        today = _load_shop_today(conn, report)
        _require_ticket(conn, ticket_id)
        vendor = conn.execute("SELECT id, name, lead_days FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if vendor is None:
            raise RecordNotFound(f"No vendor with id {vendor_id}.", existing_vendor_ids=_existing(conn, "SELECT id FROM vendors ORDER BY id"))
        item = conn.execute(
            "SELECT sku, size FROM inventory WHERE upper(sku) = upper(?) AND upper(size) = upper(?)", (sku, size)
        ).fetchone()
        if item is None:
            raise RecordNotFound(f"No inventory row for {sku} size {size}.")
        price = conn.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (item["sku"],)).fetchone()
        if price is None:
            raise Refused("no_price", f"pricing has no row for {item['sku']}, so the cost can't be estimated.")
        existing = conn.execute(
            "SELECT id FROM purchase_requests WHERE ticket_id = ? AND sku = ? AND size = ? AND status = ?",
            (ticket_id, item["sku"], item["size"], REQUEST_PENDING),
        ).fetchone()
        if existing:
            raise Refused("duplicate", f"Purchase request {existing['id']} for this item and ticket is already waiting.", existing_request_id=existing["id"])

        hold = _vendor_hold(conn, vendor_id, today, report)
        on_hold = not hold["vendor_will_ship_new_products"]
        arrival = None if on_hold else _earliest_arrival(today, vendor["lead_days"], report)
        unit_cost = float(price["unit_cost"])
        estimated = unit_cost * quantity
        cur = conn.execute(
            "INSERT INTO purchase_requests (vendor_id, sku, size, quantity, unit_cost, estimated_cost, ticket_id, vendor_on_hold, expected_arrival, reason, requested_by, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (vendor_id, item["sku"], item["size"], quantity, unit_cost, estimated, ticket_id, int(on_hold), arrival, reason, who, REQUEST_PENDING, _now()),
        )
        _note(conn, ticket_id, who, f"Prepared purchase request {cur.lastrowid}: {quantity} x {item['sku']} {item['size']} from {vendor['name']}, est. {estimated:.2f}. Waiting for human decision.")
        report.gap("The database does not link products to vendors; the vendor was chosen by the requesting agent.")
        report.assume("Estimated cost = quantity x pricing.unit_cost. No vendor quote is recorded.")
        return {
            "purchase_request": {
                "id": cur.lastrowid,
                "status": REQUEST_PENDING,
                "vendor": vendor["name"],
                "sku": item["sku"],
                "size": item["size"],
                "quantity": quantity,
                "unit_cost": _money(unit_cost),
                "estimated_cost": _money(estimated),
                "vendor_on_hold": on_hold,
                "blocking_invoice_ids": hold["blocking_invoice_ids"],
                "expected_arrival": arrival,
                "requested_by": who,
            },
            "next_step": (
                "A human decides this in the approval process. No vendor is contacted."
                + (" The vendor will not ship until its unpaid invoices are paid." if on_hold else "")
            ),
        }

    return _run(tool, ["purchase_requests", "vendors", "invoices", "inventory", "pricing", "tickets", "ticket_notes", "desk"], work, write=True)


def save_draft_message(
    ticket_id: Annotated[int, Field(ge=1, description="The ticket this message is about.")],
    recipient_type: Annotated[Literal["customer", "vendor", "landlord"], Field(description="Who the message would go to.")],
    recipient_name: Annotated[str, Field(min_length=1, max_length=80, description="Name as recorded on the ticket, vendor or lease.")],
    subject: Annotated[str, Field(min_length=1, max_length=150, description="Subject line.")],
    body: Annotated[str, Field(min_length=1, max_length=2000, description="Message text.")],
    author: Annotated[str, Field(description="The agent writing the draft.")],
) -> dict[str, Any]:
    """Save a message draft on the ticket board. Nothing is sent.

    Drafts stay on the board for a human to review. There is no tool that sends
    email or contacts customers, vendors or landlords.
    """
    tool = "save_draft_message"
    try:
        ticket_id = _positive_int("ticket_id", ticket_id)
        recipient_type = _choice("recipient_type", recipient_type, ("customer", "vendor", "landlord"))
        recipient_name = _text("recipient_name", recipient_name, max_length=80)
        subject = _text("subject", subject, max_length=150)
        body = _text("body", body, max_length=2000)
    except ToolInputError as exc:
        return _error(tool, "invalid_input", str(exc))

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        who = _agent("author", author, AGENT_NAMES)
        _load_shop_today(conn, report)
        _require_ticket(conn, ticket_id)
        cur = conn.execute(
            "INSERT INTO message_drafts (ticket_id, recipient_type, recipient_name, subject, body, author, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticket_id, recipient_type, recipient_name, subject, body, who, _now()),
        )
        _note(conn, ticket_id, who, f"Saved draft {cur.lastrowid} to {recipient_type} {recipient_name} (not sent).")
        report.assume(NOT_SENT)
        return {"draft": {"id": cur.lastrowid, "status": "draft", "sent": False, "recipient_type": recipient_type, "recipient_name": recipient_name, "subject": subject}}

    return _run(tool, ["message_drafts", "tickets", "ticket_notes", "desk"], work, write=True)


def update_ticket_status(
    ticket_id: Annotated[int, Field(ge=1, description="The ticket to update.")],
    new_status: Annotated[Literal["open", "in_progress", "awaiting_approval", "resolved"], Field(description="The ticket's new status.")],
    note: Annotated[str, Field(min_length=1, max_length=1000, description="What was decided and why.")],
    updated_by: Annotated[str, Field(description="The agent making the change. Only the boss may.")],
) -> dict[str, Any]:
    """Change a ticket's status on the board and record why. Only the Boss may do this."""
    tool = "update_ticket_status"
    try:
        ticket_id = _positive_int("ticket_id", ticket_id)
        new_status = _choice("new_status", new_status, TICKET_STATUSES)
        note = _text("note", note, max_length=1000)
    except ToolInputError as exc:
        return _error(tool, "invalid_input", str(exc))

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        who = _agent("updated_by", updated_by, TICKET_STATUS_SETTERS)
        _load_shop_today(conn, report)
        before = _require_ticket(conn, ticket_id)["status"]
        conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (new_status, ticket_id))
        _note(conn, ticket_id, who, note, status_after=new_status)
        return {"ticket_id": ticket_id, "status_before": before, "status_after": new_status}

    return _run(tool, ["tickets", "ticket_notes", "desk"], work, write=True)


# =========================================================================== #
# APPROVER-MODE TOOLS: only registered with --approver (the human process)
# =========================================================================== #


def execute_approved_payment(
    payment_request_id: Annotated[int, Field(ge=1, description="The pending payment request a human has approved.")],
    approved_by: Annotated[str, Field(min_length=1, max_length=80, description="The human approver's name.")],
) -> dict[str, Any]:
    """HUMAN APPROVAL ONLY. Execute a pending payment request a human has approved.

    In one transaction: re-checks that the invoice is still unpaid or the rent
    still due as recorded, refuses if the account balance is less than the
    amount (no negative balances), records the payment, lowers the balance,
    marks the invoice 'paid' or moves the lease's next_due on one month, and
    marks the request 'executed'. If the bill changed or the cash no longer
    covers it, no money moves and the request is marked 'failed' with the reason.
    """
    tool = "execute_approved_payment"
    try:
        payment_request_id = _positive_int("payment_request_id", payment_request_id)
    except ToolInputError as exc:
        return _error(tool, "invalid_input", str(exc))

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        human = _human("approved_by", approved_by)
        today = _load_shop_today(conn, report)
        req = conn.execute("SELECT * FROM payment_requests WHERE id = ?", (payment_request_id,)).fetchone()
        if req is None:
            raise RecordNotFound(f"No payment request with id {payment_request_id}.")
        if req["status"] != REQUEST_PENDING:
            raise Refused("not_pending", f"Payment request {payment_request_id} is {req['status']!r}, not pending.")
        amount = float(req["amount"])

        def fail(reason: str, message: str, **details: Any) -> Refused:
            """Record the failed attempt on the request (no money moves), then refuse."""
            conn.execute(
                "UPDATE payment_requests SET status = 'failed', decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?",
                (human, _now(), message, payment_request_id),
            )
            _note(conn, req["ticket_id"], f"human:{human}", f"Approval of payment request {payment_request_id} failed: {message}")
            return Refused(reason, message, commit=True, payment_request_status="failed", **details)

        # The thing being paid must still be exactly as it was when the request was prepared.
        if req["payment_type"] == "vendor_invoice":
            src = conn.execute("SELECT amount, status FROM invoices WHERE id = ?", (req["reference_id"],)).fetchone()
            if src is None or src["status"] != OUTSTANDING_INVOICE_STATUS or float(src["amount"]) != amount:
                raise fail("stale_request", "The invoice is no longer unpaid at this amount. Prepare a new request.")
        else:
            src = conn.execute("SELECT monthly_rent, next_due FROM leases WHERE id = ?", (req["reference_id"],)).fetchone()
            if src is None or src["next_due"] != req["due_date"] or float(src["monthly_rent"]) != amount:
                raise fail("stale_request", "The lease's rent or due date has changed since the request. Prepare a new request.")

        # Cash is re-read here, inside the payment transaction, not taken from the request.
        acct = conn.execute("SELECT name, balance FROM cash_accounts WHERE name = ?", (req["account"],)).fetchone()
        if acct is None:
            raise RecordNotFound(f"Cash account {req['account']!r} no longer exists.")
        before = float(acct["balance"])
        if before < amount:
            raise fail(
                "insufficient_funds",
                f"Refused: paying {amount:.2f} from {acct['name']} would take the balance from {before:.2f} to {before - amount:.2f}. Balances may not go below zero.",
                balance=_money(before),
                amount=_money(amount),
            )

        paid_at = today.isoformat() if today else _now()[:10]
        kind = "invoice" if req["payment_type"] == "vendor_invoice" else "rent"
        cur = conn.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, ?, ?, ?)",
            (kind, req["reference_id"], amount, acct["name"], paid_at, human),
        )
        # The balance guard is repeated in the UPDATE itself, so it can't go negative.
        updated = conn.execute(
            "UPDATE cash_accounts SET balance = balance - ? WHERE name = ? AND balance >= ?",
            (amount, acct["name"], amount),
        ).rowcount
        if updated != 1:
            raise Refused("insufficient_funds", "Balance check failed at the moment of payment; nothing was paid.")

        change: dict[str, Any]
        if kind == "invoice":
            conn.execute("UPDATE invoices SET status = ? WHERE id = ?", (PAID_INVOICE_STATUS, req["reference_id"]))
            change = {"invoice_id": req["reference_id"], "invoice_status": PAID_INVOICE_STATUS}
        else:
            old_due = _parse_date(req["due_date"])
            if old_due is None:
                raise Refused("bad_due_date", f"Lease next_due {req['due_date']!r} is not a date; can't advance it.")
            new_due = _add_one_month(old_due).isoformat()
            conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (new_due, req["reference_id"]))
            change = {"lease_id": req["reference_id"], "next_due_before": req["due_date"], "next_due_after": new_due}
            report.assume("After rent is paid, leases.next_due moves forward one calendar month.")

        conn.execute(
            "UPDATE payment_requests SET status = 'executed', decided_by = ?, decided_at = ?, payment_id = ? WHERE id = ?",
            (human, _now(), cur.lastrowid, payment_request_id),
        )
        _note(conn, req["ticket_id"], f"human:{human}", f"Approved and executed payment request {payment_request_id}: {amount:.2f} to {req['payee']} (payment {cur.lastrowid}).")
        report.assume("payments.paid_at is the shop's today (desk.date_today).")
        return {
            "payment": {"id": cur.lastrowid, "kind": kind, "ref_id": req["reference_id"], "amount": _money(amount), "account": acct["name"], "paid_at": paid_at, "approved_by": human},
            "balance_before": _money(before),
            "balance_after": _money(before - amount),
            "record_changes": change,
            "payment_request": {"id": payment_request_id, "status": "executed"},
        }

    return _run(tool, ["payment_requests", "payments", "cash_accounts", "invoices", "leases", "ticket_notes", "desk"], work, write=True)


def reject_payment_request(
    payment_request_id: Annotated[int, Field(ge=1, description="The pending payment request.")],
    rejected_by: Annotated[str, Field(min_length=1, max_length=80, description="The human's name.")],
    reason: Annotated[str, Field(min_length=1, max_length=500, description="Why it was rejected.")],
) -> dict[str, Any]:
    """HUMAN APPROVAL ONLY. Reject a pending payment request. No money moves."""
    tool = "reject_payment_request"
    try:
        payment_request_id = _positive_int("payment_request_id", payment_request_id)
        reason = _text("reason", reason, max_length=500)
    except ToolInputError as exc:
        return _error(tool, "invalid_input", str(exc))

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        human = _human("rejected_by", rejected_by)
        _load_shop_today(conn, report)
        req = conn.execute("SELECT id, status, ticket_id FROM payment_requests WHERE id = ?", (payment_request_id,)).fetchone()
        if req is None:
            raise RecordNotFound(f"No payment request with id {payment_request_id}.")
        if req["status"] != REQUEST_PENDING:
            raise Refused("not_pending", f"Payment request {payment_request_id} is {req['status']!r}, not pending.")
        conn.execute(
            "UPDATE payment_requests SET status = 'rejected', decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?",
            (human, _now(), reason, payment_request_id),
        )
        _note(conn, req["ticket_id"], f"human:{human}", f"Rejected payment request {payment_request_id}: {reason}")
        return {"payment_request": {"id": payment_request_id, "status": "rejected", "decided_by": human}}

    return _run(tool, ["payment_requests", "ticket_notes", "desk"], work, write=True)


def decide_purchase_request(
    purchase_request_id: Annotated[int, Field(ge=1, description="The pending purchase request.")],
    decision: Annotated[Literal["approve", "reject"], Field(description="approve or reject.")],
    decided_by: Annotated[str, Field(min_length=1, max_length=80, description="The human's name.")],
    note: Annotated[str, Field(max_length=500, description="Optional note.")] = "",
) -> dict[str, Any]:
    """HUMAN APPROVAL ONLY. Approve or reject a restock purchase request.

    Records the decision only. No vendor is contacted and no money moves; the
    vendor's eventual invoice is paid through a payment request like any other.
    """
    tool = "decide_purchase_request"
    try:
        purchase_request_id = _positive_int("purchase_request_id", purchase_request_id)
        decision = _choice("decision", decision, ("approve", "reject"))
    except ToolInputError as exc:
        return _error(tool, "invalid_input", str(exc))

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        human = _human("decided_by", decided_by)
        _load_shop_today(conn, report)
        req = conn.execute("SELECT id, status, ticket_id, vendor_on_hold FROM purchase_requests WHERE id = ?", (purchase_request_id,)).fetchone()
        if req is None:
            raise RecordNotFound(f"No purchase request with id {purchase_request_id}.")
        if req["status"] != REQUEST_PENDING:
            raise Refused("not_pending", f"Purchase request {purchase_request_id} is {req['status']!r}, not pending.")
        status = "approved" if decision == "approve" else "rejected"
        conn.execute(
            "UPDATE purchase_requests SET status = ?, decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?",
            (status, human, _now(), (note or "").strip() or None, purchase_request_id),
        )
        _note(conn, req["ticket_id"], f"human:{human}", f"{status.capitalize()} purchase request {purchase_request_id}. {note}".strip())
        report.assume("A purchase decision is a record only. No vendor is contacted and no money moves.")
        return {"purchase_request": {"id": purchase_request_id, "status": status, "decided_by": human, "vendor_on_hold": bool(req["vendor_on_hold"])}}

    return _run(tool, ["purchase_requests", "ticket_notes", "desk"], work, write=True)


def add_human_note(
    ticket_id: Annotated[int, Field(ge=1, description="The ticket the note is about.")],
    author: Annotated[str, Field(min_length=1, max_length=80, description="The human's name.")],
    note: Annotated[str, Field(min_length=1, max_length=1000, description="The decision or instruction for the team.")],
) -> dict[str, Any]:
    """HUMAN ONLY. Record a note or decision from a person on a ticket.

    Stored in ticket_notes with author 'human:<name>'. Agents read these through
    get_ticket_details. Only the approval process can write them, so an agent can
    never put words in a human's mouth.
    """
    tool = "add_human_note"
    try:
        ticket_id = _positive_int("ticket_id", ticket_id)
        note = _text("note", note, max_length=1000)
    except ToolInputError as exc:
        return _error(tool, "invalid_input", str(exc))

    def work(conn: sqlite3.Connection, report: _Report) -> dict[str, Any]:
        human = _human("author", author)
        _load_shop_today(conn, report)
        _require_ticket(conn, ticket_id)
        _note(conn, ticket_id, f"human:{human}", note)
        return {"ticket_id": ticket_id, "author": f"human:{human}", "note": note}

    return _run(tool, ["ticket_notes", "tickets", "desk"], work, write=True)


# --------------------------------------------------------------------------- #
# Registration and entry point
# --------------------------------------------------------------------------- #

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
PREPARE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
MONEY = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)

AGENT_READ_TOOLS = (
    list_ticket_board,
    get_ticket_details,
    get_invoice_and_vendor_status,
    get_rent_payment_status,
    get_stock_and_price_quote,
    list_vendors_with_status,
    check_cash_for_amount,
    get_cash_position,
    list_pending_approvals,
)
AGENT_PREPARE_TOOLS = (prepare_payment_request, prepare_purchase_request, save_draft_message, update_ticket_status)
APPROVER_TOOLS = (execute_approved_payment, reject_payment_request, decide_purchase_request, add_human_note)


def register_tools(approver: bool) -> None:
    for fn in AGENT_READ_TOOLS:
        mcp.tool(fn, annotations=READ_ONLY)
    for fn in AGENT_PREPARE_TOOLS:
        mcp.tool(fn, annotations=PREPARE)
    if approver:
        for fn in APPROVER_TOOLS:
            mcp.tool(fn, annotations=MONEY if fn is execute_approved_payment else PREPARE)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Campus Customs MCP server (stdio).")
    parser.add_argument(
        "--approver",
        action="store_true",
        help="Also expose the human-approval tools. Only the human-approval process may start this mode.",
    )
    args = parser.parse_args()
    register_tools(approver=args.approver)
    print(f"campus-customs MCP server: {'APPROVER' if args.approver else 'agent'} mode, database {WORKING_DB_LABEL}", file=sys.stderr)
    mcp.run(show_banner=False)
