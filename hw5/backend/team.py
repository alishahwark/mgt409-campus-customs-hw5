"""Five-agent PydanticAI team with bounded MCP-only coordination."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from .agent_tools import ALL_AGENT_TOOLS
from .audit import append_audit_entry
from .llm import get_agent_model
from .limits import (
    MAX_AGENT_OUTPUT_TOKENS,
    MAX_DELEGATION_DEPTH,
    MAX_ITERATIONS_PER_TICKET,
    MAX_MCP_TOOL_CALLS_PER_AGENT_TURN,
    MAX_TOTAL_DELEGATIONS_PER_TICKET,
    MAX_TRANSIENT_RETRIES,
)
from .mcp_client import MCPClientError, MCPToolClient
from .models import (
    AgentName,
    AgentTurn,
    ActionProposal,
    ApprovalRequirement,
    Dependency,
    Finding,
    TeamRunSummary,
)
from .runtime_types import AgentDependencies, TicketContext


AGENT_NAMES: tuple[AgentName, ...] = (
    "boss",
    "inventory",
    "accounting",
    "facilities",
    "customer_service",
)
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
PROMPT_FILES = {name: PROMPT_DIR / f"{name}.md" for name in AGENT_NAMES}


def load_agent_prompt(agent_name: AgentName) -> str:
    path = PROMPT_FILES[agent_name]
    prompt = path.read_text().strip()
    if not prompt:
        raise ValueError(f"Agent prompt is empty: {path}")
    return prompt


def create_agent(agent_name: AgentName, model: Any = None) -> Agent:
    """Create one real PydanticAI Agent with the role prompt loaded from disk."""
    return Agent(
        model=model or get_agent_model(),
        name=f"campus_customs_{agent_name}",
        system_prompt=load_agent_prompt(agent_name),
        deps_type=AgentDependencies,
        output_type=AgentTurn,
        tools=ALL_AGENT_TOOLS,
        retries=MAX_TRANSIENT_RETRIES,
        model_settings={"max_tokens": MAX_AGENT_OUTPUT_TOKENS, "parallel_tool_calls": False},
    )


def create_agent_team(model: Any = None) -> dict[AgentName, Agent]:
    """Create all five agents with the same fixed Portkey model."""
    shared_model = model or get_agent_model()
    return {name: create_agent(name, shared_model) for name in AGENT_NAMES}


class TeamRuntime:
    """Coordinates agents while enforcing limits and safety rules."""

    def __init__(
        self,
        agents: dict[AgentName, Agent] | None = None,
        mcp_client: MCPToolClient | None = None,
    ) -> None:
        self.agents = agents or create_agent_team()
        self.mcp_client = mcp_client
        self.context: TicketContext | None = None

    async def mcp_tool(
        self,
        dependencies: AgentDependencies,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call MCP with per-turn limits, caching, retries, and an audit entry."""
        context = dependencies.context
        if context.stop_reason is not None:
            return {"ok": False, "error": f"Ticket run already stopped: {context.stop_reason}."}
        cache_key = json.dumps(
            [tool_name, arguments], sort_keys=True, separators=(",", ":")
        )
        if cache_key in context.mcp_cache:
            result = context.mcp_cache[cache_key]
            self._register_verified_guards(tool_name, result)
            append_audit_entry(
                ticket_id=dependencies.ticket_id,
                agent_name=dependencies.agent_name,
                action="mcp_cache_hit",
                arguments={"tool": tool_name, "arguments": arguments},
                result=result,
                iteration=context.iteration,
                delegation_depth=context.delegation_depth,
                status=context.status,
            )
            return result

        if context.mcp_calls_this_turn >= MAX_MCP_TOOL_CALLS_PER_AGENT_TURN:
            result = {
                "ok": False,
                "error": "Maximum MCP tool calls per agent turn reached.",
            }
            context.status = "blocked"
            context.stop_reason = "mcp_tool_call_limit"
            append_audit_entry(
                ticket_id=dependencies.ticket_id,
                agent_name=dependencies.agent_name,
                action="mcp_tool_limit",
                arguments={"tool": tool_name},
                result=result,
                iteration=context.iteration,
                delegation_depth=context.delegation_depth,
                status=context.status,
                stop_reason=context.stop_reason,
            )
            return result

        if self.mcp_client is None:
            raise MCPClientError("TeamRuntime has no MCP client")
        context.mcp_calls_this_turn += 1
        last_error: str | None = None
        for attempt in range(MAX_TRANSIENT_RETRIES + 1):
            try:
                result = await self.mcp_client.call(tool_name, arguments)
                context.mcp_cache[cache_key] = result
                self._register_verified_guards(tool_name, result)
                append_audit_entry(
                    ticket_id=dependencies.ticket_id,
                    agent_name=dependencies.agent_name,
                    action="mcp_tool_call",
                    arguments={"tool": tool_name, "arguments": arguments},
                    result=result,
                    iteration=context.iteration,
                    delegation_depth=context.delegation_depth,
                    status=context.status,
                )
                return result
            except Exception as exc:  # retry policy is intentionally bounded
                last_error = str(exc)
                if attempt == MAX_TRANSIENT_RETRIES:
                    break
        result = {"ok": False, "error": f"MCP call failed after retries: {last_error}"}
        context.status = "blocked"
        context.stop_reason = "mcp_failure"
        append_audit_entry(
            ticket_id=dependencies.ticket_id,
            agent_name=dependencies.agent_name,
            action="mcp_tool_failure",
            arguments={"tool": tool_name, "arguments": arguments},
            result=result,
            iteration=context.iteration,
            delegation_depth=context.delegation_depth,
            status=context.status,
            stop_reason=context.stop_reason,
        )
        return result

    def _register_verified_guards(
        self,
        tool_name: str,
        result: dict[str, Any],
    ) -> None:
        """Persist safety facts returned by MCP for backend enforcement."""
        if self.context is None:
            return
        if isinstance(result.get("available_cash"), (int, float)):
            self.context.available_cash = float(result["available_cash"])
        for invoice in result.get("open_unpaid_invoices", []):
            if isinstance(invoice, dict) and invoice.get("vendor_id") is not None:
                self.context.vendor_restrictions[int(invoice["vendor_id"])] = True
        for invoice in result.get("open_invoice_obligations", []):
            if isinstance(invoice, dict) and invoice.get("vendor_id") is not None:
                self.context.vendor_restrictions[int(invoice["vendor_id"])] = True
        if tool_name == "get_vendor_details":
            restricted = result.get("can_ship_new_products") is False
            for vendor in result.get("vendors", []):
                if isinstance(vendor, dict) and vendor.get("id") is not None:
                    self.context.vendor_restrictions[int(vendor["id"])] = restricted

    async def delegate(
        self,
        *,
        source_agent: AgentName,
        target_agent: AgentName,
        ticket_id: int,
        task: str,
        depth: int,
    ) -> dict[str, Any]:
        """Delegate once, with cycle, depth, count, and iteration guards."""
        if self.context is None:
            return {"ok": False, "error": "No ticket context is active."}
        context = self.context
        if context.stop_reason is not None:
            return {"ok": False, "error": f"Ticket run already stopped: {context.stop_reason}."}
        task_key = hashlib.sha256(task.strip().lower().encode()).hexdigest()[:16]
        delegation_key = (source_agent, target_agent, task_key)
        if source_agent == target_agent:
            return {"ok": False, "error": "Self-delegation is not allowed."}
        if target_agent in context.active_agents:
            return {"ok": False, "error": "Circular delegation suppressed."}
        if depth > MAX_DELEGATION_DEPTH:
            return {"ok": False, "error": "Maximum delegation depth reached."}
        if context.total_delegations >= MAX_TOTAL_DELEGATIONS_PER_TICKET:
            context.status = "blocked"
            context.stop_reason = "delegation_limit"
            return {"ok": False, "error": "Maximum total delegations reached."}
        if delegation_key in context.seen_delegations:
            return {"ok": False, "error": "Duplicate delegation suppressed."}
        if context.iteration >= MAX_ITERATIONS_PER_TICKET:
            context.status = "blocked"
            context.stop_reason = "iteration_limit"
            return {"ok": False, "error": "Maximum ticket iterations reached."}

        context.seen_delegations.add(delegation_key)
        context.total_delegations += 1
        previous_depth = context.delegation_depth
        context.delegation_depth = depth
        append_audit_entry(
            ticket_id=ticket_id,
            agent_name=source_agent,
            action="delegation",
            arguments={"target_agent": target_agent, "task": task},
            result={"status": "started"},
            iteration=context.iteration,
            delegation_depth=depth,
            status=context.status,
        )
        try:
            turn = await self._run_agent(target_agent, task, depth)
            return {"ok": True, "turn": turn.model_dump(mode="json")}
        finally:
            context.delegation_depth = previous_depth

    async def _run_agent(
        self,
        agent_name: AgentName,
        task: str,
        depth: int,
    ) -> AgentTurn:
        if self.context is None:
            raise RuntimeError("No ticket context is active")
        context = self.context
        if agent_name in context.active_agents:
            return self._blocked_turn(agent_name, "Circular delegation suppressed.")
        context.iteration += 1
        context.mcp_calls_this_turn = 0
        if context.iteration > MAX_ITERATIONS_PER_TICKET:
            context.status = "blocked"
            context.stop_reason = "iteration_limit"
            return self._blocked_turn(agent_name, "Maximum ticket iterations reached.")

        context.active_agents.add(agent_name)
        dependencies = AgentDependencies(
            ticket_id=context.ticket_id,
            agent_name=agent_name,
            runtime=self,
            context=context,
        )
        prompt = self._build_task_prompt(task)
        append_audit_entry(
            ticket_id=context.ticket_id,
            agent_name=agent_name,
            action="agent_start",
            arguments={"task": task},
            result=None,
            iteration=context.iteration,
            delegation_depth=depth,
            status=context.status,
        )
        try:
            result = await self.agents[agent_name].run(prompt, deps=dependencies)
            turn = result.output
            self._apply_safety_rules(turn)
            self._merge_turn(turn)
            append_audit_entry(
                ticket_id=context.ticket_id,
                agent_name=agent_name,
                action="agent_result",
                arguments=None,
                result=turn.model_dump(mode="json"),
                iteration=context.iteration,
                delegation_depth=depth,
                approval_required=bool(turn.approval_requirements),
                status=turn.status,
            )
            for request in turn.delegations:
                if context.status not in {"blocked", "needs_approval"}:
                    await self.delegate(
                        source_agent=agent_name,
                        target_agent=request.target_agent,
                        ticket_id=request.ticket_id,
                        task=request.task,
                        depth=depth + 1,
            )
            return turn
        except Exception as exc:
            context.status = "blocked"
            context.stop_reason = "agent_failure"
            turn = self._blocked_turn(agent_name, f"Agent execution failed: {exc}")
            append_audit_entry(
                ticket_id=context.ticket_id,
                agent_name=agent_name,
                action="agent_failure",
                result={"error": str(exc)},
                iteration=context.iteration,
                delegation_depth=depth,
                status=turn.status,
                stop_reason=context.stop_reason,
            )
            return turn
        finally:
            context.active_agents.discard(agent_name)

    def _build_task_prompt(self, task: str) -> str:
        if self.context is None:
            return task
        context = self.context
        facts = [finding.model_dump(mode="json") for finding in context.facts[-12:]]
        return (
            f"Ticket ID: {context.ticket_id}.\n"
            f"Iteration: {context.iteration}/{MAX_ITERATIONS_PER_TICKET}.\n"
            f"Task: {task}\n"
            "Verified context (use MCP for anything missing): "
            f"{json.dumps(facts, separators=(',', ':'))}"
        )

    def _apply_safety_rules(self, turn: AgentTurn) -> None:
        """Enforce safety even if an agent output violates its prompt."""
        context = self.context
        if context is None:
            return
        for action in turn.proposed_actions:
            if action.action_type in {
                "payment",
                "purchase_order",
                "restock",
                "external_contact",
            }:
                action.requires_human_approval = True
                turn.approval_requirements.append(
                    ApprovalRequirement(
                        action=action.action,
                        reason="Sensitive action requires explicit human approval.",
                    )
                )
            if action.action_type == "external_contact":
                turn.status = "blocked"
                turn.dependencies.append(
                    Dependency(
                        description="External contact is prohibited; keep communication as a draft.",
                        owner=turn.assigned_agent,
                    )
                )
            if action.action_type in {"purchase_order", "restock"} and action.vendor_has_open_unpaid_invoices is True:
                turn.status = "blocked"
                turn.dependencies.append(
                    Dependency(
                        description="Vendor has open unpaid invoices and cannot ship new products.",
                        owner="inventory",
                    )
                )
            if (
                action.action_type in {"purchase_order", "restock"}
                and action.vendor_id is not None
                and context.vendor_restrictions.get(action.vendor_id) is True
            ):
                turn.status = "blocked"
                turn.dependencies.append(
                    Dependency(
                        description="MCP verified that this vendor has open unpaid invoices.",
                        owner="inventory",
                    )
                )
            if action.amount is not None and action.action_type in {
                "payment",
                "purchase_order",
                "restock",
            }:
                verified_cash = context.available_cash
                if verified_cash is None:
                    turn.status = "blocked"
                    turn.dependencies.append(
                        Dependency(
                            description="Verified cash position is required before proposing this amount.",
                            owner="accounting",
                        )
                    )
                elif action.amount > verified_cash:
                    turn.status = "blocked"
                    turn.dependencies.append(
                        Dependency(
                            description="Proposed amount exceeds MCP-verified available cash.",
                            owner="accounting",
                        )
                    )
            if (
                action.amount is not None
                and action.available_cash is not None
                and action.amount > action.available_cash
            ):
                turn.status = "blocked"
                turn.dependencies.append(
                    Dependency(
                        description="Proposed amount exceeds verified available cash.",
                        owner="accounting",
                    )
                )
        blocking = any(item.blocking and not item.resolved for item in turn.dependencies)
        incomplete = any(not item.completed for item in turn.proposed_actions)
        if turn.status == "completed" and (blocking or incomplete or turn.approval_requirements):
            turn.status = "needs_approval" if turn.approval_requirements else "blocked"

    def _merge_turn(self, turn: AgentTurn) -> None:
        if self.context is None:
            return
        # A model's final structured status cannot erase a hard runtime stop
        # raised by a tool/delegation limit or failed MCP call.
        if self.context.stop_reason is not None:
            turn.status = "blocked"
            turn.dependencies.append(
                Dependency(description=f"Runtime stopped: {self.context.stop_reason}.", owner=turn.assigned_agent)
            )
        self.context.facts.extend(turn.findings)
        self.context.turns.append(turn)
        self.context.proposed_actions.extend(
            action.model_dump(mode="json") for action in turn.proposed_actions
        )
        self.context.dependencies.extend(
            dependency.model_dump(mode="json") for dependency in turn.dependencies
        )
        self.context.approvals.extend(
            approval.model_dump(mode="json")
            for approval in turn.approval_requirements
        )
        self.context.status = turn.status
        self.context.completed_agents.add(turn.assigned_agent)

    def _blocked_turn(self, agent_name: AgentName, reason: str) -> AgentTurn:
        return AgentTurn(
            ticket_id=self.context.ticket_id if self.context else 0,
            assigned_agent=agent_name,
            status="blocked",
            dependencies=[Dependency(description=reason, owner=agent_name)],
            final_reasoning=reason,
        )

    async def run_ticket(
        self,
        ticket_id: int,
        task: str | None = None,
    ) -> TeamRunSummary:
        """Run a bounded Boss-led workflow; callers may inject mocked agents."""
        self.context = TicketContext(ticket_id=ticket_id)
        client_was_injected = self.mcp_client is not None
        if client_was_injected:
            turn = await self._run_agent(
                "boss",
                task or "Inspect and coordinate this ticket using verified MCP findings.",
                0,
            )
            return self._summary(turn)

        async with MCPToolClient() as client:
            self.mcp_client = client
            turn = await self._run_agent(
                "boss",
                task or "Inspect and coordinate this ticket using verified MCP findings.",
                0,
            )
            return self._summary(turn)

    def _summary(self, turn: AgentTurn) -> TeamRunSummary:
        context = self.context
        assert context is not None
        return TeamRunSummary(
            ticket_id=context.ticket_id,
            status=context.status if context.status != "in_progress" else turn.status,
            final_reasoning=turn.final_reasoning,
            findings=context.facts,
            proposed_actions=[ActionProposal.model_validate(item) for item in context.proposed_actions],
            dependencies=[Dependency.model_validate(item) for item in context.dependencies],
            approval_requirements=[
                ApprovalRequirement.model_validate(item) for item in context.approvals
            ],
            iterations=context.iteration,
            delegations=context.total_delegations,
            stop_reason=context.stop_reason,
        )
