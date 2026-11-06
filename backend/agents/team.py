"""The team: builds the five agents, connects them to MCP, and lets them ask each other.

How a ticket runs
-----------------
handle_ticket(ticket_id) starts the Boss. The Boss reads the ticket through MCP
and, if it needs help, calls ask_colleague(colleague, request). That runs the
colleague as a nested agent run and returns its AgentReport. Any agent can call
ask_colleague, so specialists can consult each other (Inventory asking
Accounting whether a vendor can be paid, for example).

Loop protection, checked before every delegation
------------------------------------------------
* no asking yourself;
* no asking an agent that is already waiting on you (anyone in the call chain).
  That covers asking the Boss back mid-task: you return your question in
  open_questions instead;
* a maximum delegation depth (boss -> specialist -> specialist);
* a maximum number of delegations per ticket;
* the same request to the same colleague gets the earlier answer back from a
  cache instead of a new run.

Every agent run on the ticket shares one usage counter, so the request, tool-call
and token limits apply to the whole ticket, not to each agent separately.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import RunUsage, UsageLimits

from .. import audit
from ..config import PROMPTS_DIR, build_model, model_settings
from ..mcp_connection import build_shop_toolset
from ..models import AGENT_NAMES, AgentName, AgentReport, RunLimits, TeamDeps, TicketOutcome, TicketRun
from . import ROLES
from .role import RoleSpec


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


class Team:
    def __init__(self, limits: RunLimits | None = None) -> None:
        self.limits = limits or RunLimits()
        self.toolset = build_shop_toolset()
        self.agents: dict[AgentName, Agent[TeamDeps, Any]] = {name: self._build(role) for name, role in ROLES.items()}

    # ------------------------------------------------------------------ #
    # Building one agent
    # ------------------------------------------------------------------ #

    def _build(self, role: RoleSpec) -> Agent[TeamDeps, Any]:
        prompt = (PROMPTS_DIR / role.prompt_file).read_text(encoding="utf-8")
        allowed = role.mcp_tools
        agent: Agent[TeamDeps, Any] = Agent(
            build_model(),
            name=role.name,
            deps_type=TeamDeps,
            output_type=role.output_type,
            instructions=prompt,
            toolsets=[self.toolset.filtered(lambda ctx, tool_def: tool_def.name in allowed)],
            model_settings=model_settings(self.limits.max_output_tokens_per_reply),
            retries=1,
        )

        @agent.instructions
        def situation(ctx: RunContext[TeamDeps]) -> str:
            deps, run = ctx.deps, ctx.deps.run
            waiting = " -> ".join(deps.chain[:-1]) or "nobody (you started this ticket)"
            others = "\n".join(
                f"- {r.name}: {r.expertise}" for r in ROLES.values() if r.name != role.name
            )
            return (
                f"You are the {role.title} agent ('{role.name}'). Ticket: {run.ticket_id}.\n"
                f"Waiting on your answer: {waiting}. Do not call ask_colleague for any of them; "
                "put questions for them in your report instead.\n"
                f"Delegation depth {deps.depth} of {run.limits.max_delegation_depth}; "
                f"delegations used {run.delegations} of {run.limits.max_delegations}; "
                f"MCP tool calls used {run.mcp_tool_calls} of {run.limits.max_tool_calls}.\n"
                f"Colleagues you can ask with ask_colleague:\n{others}"
            )

        @agent.tool
        async def ask_colleague(ctx: RunContext[TeamDeps], colleague: AgentName, request: str) -> dict[str, Any]:
            """Ask another agent to do something within its role and report back.

            Be specific: say what you need, which records it concerns, and what you
            will do with the answer. Returns that agent's report.
            """
            return await self._delegate(ctx, colleague, request)

        return agent

    # ------------------------------------------------------------------ #
    # Delegation with loop protection
    # ------------------------------------------------------------------ #

    async def _delegate(self, ctx: RunContext[TeamDeps], colleague: AgentName, request: str) -> dict[str, Any]:
        deps, run = ctx.deps, ctx.deps.run
        args = {"colleague": colleague, "request": request}

        def refuse(reason: str) -> dict[str, Any]:
            audit.log("delegation_refused", run=run, agent=deps.agent, deps=deps, action="ask_colleague", args=args, reason=reason, usage=ctx.usage)
            return {"delegation_refused": True, "reason": reason}

        if colleague not in AGENT_NAMES:
            return refuse(f"'{colleague}' is not an agent. Choose from {', '.join(AGENT_NAMES)}.")
        if colleague == deps.agent:
            return refuse("You cannot ask yourself. Do the work or report back.")
        if colleague in deps.chain:
            return refuse(
                f"{colleague} is already waiting on your answer, so asking them would loop. "
                "Put your question in open_questions and report back."
            )
        if deps.depth >= run.limits.max_delegation_depth:
            return refuse("Maximum delegation depth reached. Answer with what you have and report back.")
        key = (deps.agent, colleague, _normalise(request))
        if key in run.answered:
            audit.log("delegation_refused", run=run, agent=deps.agent, deps=deps, action="ask_colleague", args=args,
                      reason="Duplicate request; returned the earlier answer.", usage=ctx.usage)
            return {"already_answered": True, "report": run.answered[key]}
        if run.delegations >= run.limits.max_delegations:
            return refuse("The delegation budget for this ticket is used up. Report back with what you have.")

        run.delegations += 1
        audit.log("delegation", run=run, agent=deps.agent, deps=deps, action="ask_colleague", args=args,
                  reason=f"{deps.agent} handed a task to {colleague}", usage=ctx.usage)
        child = TeamDeps(agent=colleague, chain=deps.chain + (colleague,), run=run)
        output = await self.run_agent(child, f"Request from {deps.agent} about ticket {run.ticket_id}:\n{request}", usage=ctx.usage)
        report = output.model_dump()
        run.answered[key] = report
        return report

    # ------------------------------------------------------------------ #
    # Running one agent, logging each step of its loop
    # ------------------------------------------------------------------ #

    def usage_limits(self) -> UsageLimits:
        return UsageLimits(
            request_limit=self.limits.max_model_requests,
            tool_calls_limit=self.limits.max_tool_calls,
            total_tokens_limit=self.limits.max_total_tokens,
        )

    async def run_agent(self, deps: TeamDeps, prompt: str, usage: RunUsage | None = None) -> Any:
        agent = self.agents[deps.agent]
        run = deps.run
        audit.log("agent_started", run=run, agent=deps.agent, deps=deps, args={"prompt": prompt}, usage=usage)
        async with agent.iter(prompt, deps=deps, usage=usage, usage_limits=self.usage_limits()) as agent_run:
            async for node in agent_run:
                if Agent.is_call_tools_node(node):
                    calls = [p for p in node.model_response.parts if getattr(p, "part_kind", "") == "tool-call"]
                    audit.log(
                        "model_step",
                        run=run,
                        agent=deps.agent,
                        deps=deps,
                        action="model_response",
                        result={"tool_calls_requested": [c.tool_name for c in calls]},
                        reason="final answer" if any(c.tool_name == "final_result" for c in calls) else None,
                        usage=agent_run.usage,
                    )
            output = agent_run.result.output
            audit.log(
                "agent_finished",
                run=run,
                agent=deps.agent,
                deps=deps,
                result={"status": getattr(output, "status", getattr(output, "final_status", None)),
                        "summary": audit.compact(getattr(output, "summary", ""))},
                reason=getattr(output, "handoff_reason", None) or "Boss returned its ticket outcome",
                usage=agent_run.usage,
            )
            return output

    # ------------------------------------------------------------------ #
    # Entry point: one ticket
    # ------------------------------------------------------------------ #

    async def handle_ticket(self, ticket_id: int, run: TicketRun | None = None) -> TicketOutcome:
        run = run or TicketRun(ticket_id=ticket_id, limits=self.limits)
        deps = TeamDeps(agent="boss", chain=("boss",), run=run)
        usage = RunUsage()
        audit.log("run_started", run=run, agent="boss", deps=deps, args={"limits": vars(self.limits)})
        try:
            async with self.toolset:
                outcome: TicketOutcome = await self.run_agent(
                    deps, f"Ticket {ticket_id} is on the board. Read it with get_ticket_details and handle it.", usage=usage
                )
        except UsageLimitExceeded as exc:
            audit.log("limit_reached", run=run, agent="boss", deps=deps, reason=str(exc), usage=usage)
            outcome = TicketOutcome(
                ticket_id=ticket_id,
                final_status="could_not_complete",
                summary=f"Stopped: {exc}. Any requests or drafts already created remain on the board.",
                next_steps_for_human=["Review the audit trail for this run and decide whether to rerun the ticket."],
            )
        audit.log("run_finished", run=run, agent="boss", deps=deps,
                  result=audit.compact(outcome.model_dump()),  # the full TicketOutcome, so the API can rebuild it after a restart
                  reason="ticket run complete", usage=usage)
        return outcome


async def _main(ticket_ids: list[int]) -> None:
    team = Team()
    for ticket_id in ticket_ids:
        outcome = await team.handle_ticket(ticket_id)
        print(json.dumps(outcome.model_dump(), indent=2))


if __name__ == "__main__":
    # Development entry point until the FastAPI backend exists:
    #   .venv/bin/python -m backend.agents.team 101
    asyncio.run(_main([int(arg) for arg in sys.argv[1:]]))
