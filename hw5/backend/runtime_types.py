"""Runtime state passed to PydanticAI tools and agents."""

from dataclasses import dataclass, field
from typing import Any

from .models import AgentName, AgentTurn, Finding


@dataclass
class TicketContext:
    ticket_id: int
    facts: list[Finding] = field(default_factory=list)
    proposed_actions: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    iteration: int = 0
    delegation_depth: int = 0
    total_delegations: int = 0
    seen_delegations: set[tuple[str, str, str]] = field(default_factory=set)
    mcp_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    available_cash: float | None = None
    vendor_restrictions: dict[int, bool] = field(default_factory=dict)
    mcp_calls_this_turn: int = 0
    completed_agents: set[str] = field(default_factory=set)
    turns: list[AgentTurn] = field(default_factory=list)
    active_agents: set[str] = field(default_factory=set)
    status: str = "in_progress"
    stop_reason: str | None = None


@dataclass
class AgentDependencies:
    ticket_id: int
    agent_name: AgentName
    runtime: Any
    context: TicketContext
