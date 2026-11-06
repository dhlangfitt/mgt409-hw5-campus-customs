"""Shared data types for the Campus Customs agent team.

Everything that crosses a boundary lives here: between agents (AgentReport,
TicketOutcome), between the team and its guardrails (RunLimits, TicketRun,
TeamDeps), and between the team and the audit log (AuditEvent).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
AGENT_NAMES: tuple[AgentName, ...] = ("boss", "inventory", "accounting", "facilities", "customer_service")


# --------------------------------------------------------------------------- #
# What agents hand back to each other
# --------------------------------------------------------------------------- #


class AgentReport(BaseModel):
    """What a specialist returns to whoever asked it (the Boss or a colleague)."""

    status: Literal["done", "needs_human_approval", "needs_boss_decision", "blocked", "could_not_complete"] = Field(
        description=(
            "done: the request is answered. needs_human_approval: you prepared a payment or "
            "purchase request that a human must approve. needs_boss_decision: a judgement call "
            "for the Boss (for example a discount level). blocked: a shop rule or missing data "
            "stops progress. could_not_complete: you ran out of turns or tools failed."
        )
    )
    summary: str = Field(description="Two to four sentences answering the request.")
    facts: list[str] = Field(
        default_factory=list,
        description="Key figures from MCP tool results, each with its source, e.g. 'M on hand: 8 (get_stock_and_price_quote)'.",
    )
    actions_taken: list[str] = Field(
        default_factory=list,
        description="Records you created, e.g. 'payment_request 1 (pending approval)', 'draft 2 (not sent)'.",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="Questions for the agent who asked you, or for the Boss, instead of asking an agent that is already waiting on you.",
    )
    handoff_reason: str = Field(description="Why you stopped here and are handing back.")


class TicketOutcome(BaseModel):
    """The Boss's final word on one ticket."""

    ticket_id: int
    final_status: Literal["resolved", "awaiting_approval", "needs_human_input", "could_not_complete"] = Field(
        description=(
            "resolved: nothing left to do. awaiting_approval: payment or purchase requests are "
            "pending a human. needs_human_input: a decision only a human can make. "
            "could_not_complete: limits or errors stopped the work."
        )
    )
    summary: str = Field(description="What happened and what was decided, in plain language.")
    agents_consulted: list[AgentName] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list, description="Decisions the Boss made, with the reason for each.")
    payment_request_ids: list[int] = Field(default_factory=list)
    purchase_request_ids: list[int] = Field(default_factory=list)
    draft_ids: list[int] = Field(default_factory=list)
    next_steps_for_human: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Guardrails shared by every agent working on one ticket
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RunLimits:
    """Budgets for one ticket, shared by every agent that works on it."""

    max_model_requests: int = 30        # model calls, all agents together
    max_tool_calls: int = 40            # MCP + delegation calls, all agents together
    max_total_tokens: int = 150_000     # input + output tokens, all agents together
    max_output_tokens_per_reply: int = 1_500
    max_delegation_depth: int = 3       # boss -> specialist -> specialist, then no further
    max_delegations: int = 6            # ask_colleague calls per ticket


@dataclass
class TicketRun:
    """Mutable state for one ticket run, shared across all agents in it."""

    ticket_id: int
    limits: RunLimits = field(default_factory=RunLimits)
    run_id: str = field(default_factory=lambda: f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}")
    delegations: int = 0
    mcp_tool_calls: int = 0
    # (asker, colleague, normalised request) -> report already given, so repeats get the cached answer
    answered: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)


@dataclass
class TeamDeps:
    """Dependencies for one agent's run: who it is and who is waiting on it."""

    agent: AgentName
    chain: tuple[AgentName, ...]   # the call stack, root first; the last entry is this agent
    run: TicketRun

    @property
    def depth(self) -> int:
        return len(self.chain)


# --------------------------------------------------------------------------- #
# Audit log entries
# --------------------------------------------------------------------------- #


class AuditEvent(BaseModel):
    """One line of backend/output/audit_trail.json."""

    ts: str
    run_id: str
    ticket_id: int | None
    agent: str
    chain: list[str] = Field(default_factory=list)
    event: Literal[
        "run_started", "agent_started", "model_step", "mcp_tool_call", "tool_call_blocked",
        "delegation", "delegation_refused", "agent_finished", "limit_reached", "error", "run_finished",
        "human_decision", "database_reset",
    ]
    action: str | None = None
    args: Any = None
    result: Any = None
    reason: str | None = None
    usage: dict[str, int] | None = None


# --------------------------------------------------------------------------- #
# API shapes (backend/main.py): what the dashboard sends and receives
# --------------------------------------------------------------------------- #

RunStatus = Literal["running", "completed", "failed"]

# The lifecycle of a payment or purchase request, as the dashboard shows it:
#   proposed           an agent created it and that ticket's run is still going
#   awaiting_approval  the run has finished; waiting for a human
#   approved           a human approved a purchase (recorded; nothing is ordered or paid)
#   executed           a human approved a payment and the money moved
#   rejected           a human rejected it
#   failed             a human approved it but execution was refused (e.g. not enough cash)
ApprovalState = Literal["proposed", "awaiting_approval", "approved", "executed", "rejected", "failed"]


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    run_id: str
    ticket_id: int
    status: RunStatus
    started_at: str
    finished_at: str | None = None
    outcome: TicketOutcome | None = None
    error: str | None = None
    activity_url: str


class TicketSummary(BaseModel):
    id: int
    type: str
    requester: str
    subject: str
    status: str
    is_resolved: bool
    created_at: str
    pending_approval_requests: int
    message_drafts: int
    latest_run: RunSummary | None = None


class TicketList(BaseModel):
    shop_today: str | None
    tickets: list[TicketSummary]


class ApprovalItem(BaseModel):
    kind: Literal["payment", "purchase"]
    id: int
    ticket_id: int | None
    state: ApprovalState
    description: str
    amount: float | None
    requested_by: str
    created_at: str
    decided_by: str | None = None
    decided_at: str | None = None
    decision_note: str | None = None
    payment_id: int | None = None
    vendor_on_hold: bool | None = None


class TicketDetail(BaseModel):
    shop_today: str | None
    ticket: dict[str, Any]
    linked_records: dict[str, Any]
    notes: list[dict[str, Any]]
    message_drafts: list[dict[str, Any]]
    approvals: list[ApprovalItem]
    runs: list[RunSummary]


class StartRunResponse(BaseModel):
    run: RunSummary
    message: str


class ActivityEvent(BaseModel):
    seq: int
    ts: str
    run_id: str
    ticket_id: int | None = None
    agent: str
    event: str
    action: str | None = None
    summary: str
    chain: list[str] = Field(default_factory=list)
    args: Any = None
    result: Any = None
    reason: str | None = None
    usage: dict[str, int] | None = None


class ActivityPage(BaseModel):
    events: list[ActivityEvent]
    next_since: int
    run: RunSummary | None = None
    busy: str | None = None


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    decided_by: str = Field(min_length=1, max_length=80, description="The human making the decision.")
    note: str | None = Field(default=None, max_length=500, description="Required when rejecting.")


class NoteRequest(BaseModel):
    author: str = Field(min_length=1, max_length=80, description="The human writing the note.")
    note: str = Field(min_length=1, max_length=1000, description="A decision or instruction for the team.")


class DecisionResponse(BaseModel):
    approval: ApprovalItem
    executed: bool
    message: str
    payment: dict[str, Any] | None = None
    balance_before: float | None = None
    balance_after: float | None = None


class CashResponse(BaseModel):
    shop_today: str | None
    account: str
    balance: float
    balance_as_of: str
    accounts: list[dict[str, Any]]
    obligations_on_record: list[dict[str, Any]]
    balance_after_all_obligations: float | None
    payments: list[dict[str, Any]]


class ResetRequest(BaseModel):
    confirm: Literal["RESET"] = Field(description='Must be exactly "RESET".')


class ResetResponse(BaseModel):
    reset: bool
    message: str
    working_copy_matches_original: bool
    balance: float | None
    open_tickets: int
