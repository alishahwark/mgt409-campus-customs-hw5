"""Structured inputs and outputs shared by the Campus Customs agent team."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


AgentName = Literal[
    "boss",
    "inventory",
    "accounting",
    "facilities",
    "customer_service",
]
TicketStatus = Literal[
    "in_progress",
    "completed",
    "blocked",
    "needs_approval",
    "delegated",
    "stopped",
]
ActionType = Literal[
    "read_only",
    "draft",
    "payment",
    "purchase_order",
    "restock",
    "external_contact",
    "other",
]
ResolutionDecision = Literal[
    "unavailable_request_alternative",
    "decline_unfulfillable_bulk_request",
]


class Finding(BaseModel):
    """A concise fact backed by an MCP tool result."""

    fact: str = Field(min_length=1)
    source: str = Field(description="MCP tool name or verified workflow source")
    verified: bool = True


class Dependency(BaseModel):
    description: str = Field(min_length=1)
    owner: AgentName | None = None
    blocking: bool = True
    resolved: bool = False


class ApprovalRequirement(BaseModel):
    action: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    required: bool = True


class ActionProposal(BaseModel):
    """A proposed action; proposals are never executions."""

    action: str = Field(min_length=1)
    owner: AgentName
    action_type: ActionType = "other"
    details: str = Field(min_length=1)
    amount: float | None = Field(default=None, ge=0)
    available_cash: float | None = Field(default=None, ge=0)
    vendor_id: int | None = None
    vendor_has_open_unpaid_invoices: bool | None = None
    reference_type: Literal["invoice", "lease", "purchase"] | None = None
    reference_id: int | None = Field(default=None, ge=1)
    account: str | None = None
    requires_human_approval: bool = True
    completed: bool = False

    @model_validator(mode="after")
    def enforce_sensitive_action_approval(self) -> "ActionProposal":
        if self.action_type in {
            "payment",
            "purchase_order",
            "restock",
            "external_contact",
        }:
            self.requires_human_approval = True
        return self


class DelegationRequest(BaseModel):
    ticket_id: int
    target_agent: AgentName
    task: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    depth: int = Field(default=0, ge=0)


class AgentTurn(BaseModel):
    """Structured result returned by every PydanticAI agent."""

    ticket_id: int
    assigned_agent: AgentName
    findings: list[Finding] = Field(default_factory=list)
    proposed_actions: list[ActionProposal] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    approval_requirements: list[ApprovalRequirement] = Field(default_factory=list)
    status: TicketStatus = "in_progress"
    delegations: list[DelegationRequest] = Field(default_factory=list)
    resolution_decision: ResolutionDecision | None = None
    customer_draft: str | None = None
    final_reasoning: str = Field(min_length=1)


class TicketInput(BaseModel):
    ticket_id: int
    task: str | None = None


class TeamRunSummary(BaseModel):
    ticket_id: int
    status: TicketStatus
    final_reasoning: str
    findings: list[Finding] = Field(default_factory=list)
    proposed_actions: list[ActionProposal] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    approval_requirements: list[ApprovalRequirement] = Field(default_factory=list)
    iterations: int = 0
    delegations: int = 0
    stop_reason: str | None = None


class OperationalResolution(BaseModel):
    ticket_id: int
    decision: ResolutionDecision
    customer_draft: str
    shop_date: str
    stock_at_decision: int
    shortage_at_decision: int
    communication_status: Literal["unsent_draft"]
    fulfillment_status: Literal["not_fulfilled"]


class TicketSummary(BaseModel):
    """Ticket data exposed to the dashboard from MCP results."""

    id: int
    type: str
    requester: str
    subject: str
    description: str | None = None
    status: str
    sku: str | None = None
    size: str | None = None
    quantity: int | None = None
    lease_id: int | None = None
    invoice_id: int | None = None
    created_at: str | None = None
    resolution: OperationalResolution | None = None


class CreateTicketRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)

    @field_validator("subject", "description", mode="before")
    @classmethod
    def strip_and_validate_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if "\x00" in value:
                raise ValueError("Ticket text cannot contain a NUL character.")
        return value


class TicketsResponse(BaseModel):
    tickets: list[TicketSummary]
    shop_date: str | None = None


class RunTicketRequest(BaseModel):
    task: str | None = None


class PendingApproval(BaseModel):
    approval_id: str
    ticket_id: int
    action: str
    action_type: ActionType
    details: str
    amount: float | None = None
    account: str | None = None
    reference_type: str | None = None
    reference_id: int | None = None
    status: Literal["pending", "executing", "executed", "rejected", "failed"] = "pending"


class TicketRunResponse(BaseModel):
    ticket_id: int
    status: TicketStatus
    final_reasoning: str
    findings: list[Finding] = Field(default_factory=list)
    proposed_actions: list[ActionProposal] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    approval_requirements: list[ApprovalRequirement] = Field(default_factory=list)
    pending_approvals: list[PendingApproval] = Field(default_factory=list)
    iterations: int = 0
    delegations: int = 0
    stop_reason: str | None = None


class ApprovalDecisionRequest(BaseModel):
    """A decision made by the human using the dashboard."""

    decision: Literal["approve", "reject", "approved", "rejected"] | None = None
    approved: bool | None = None
    human_actor: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def normalize_decision(self) -> "ApprovalDecisionRequest":
        if self.decision is None and self.approved is None:
            raise ValueError("Provide decision='approve' or 'reject'.")
        normalized = self.decision
        if normalized in {"approved", "approve"}:
            normalized = "approve"
        elif normalized in {"rejected", "reject"}:
            normalized = "reject"
        if self.approved is not None:
            from_bool = "approve" if self.approved else "reject"
            if normalized is not None and normalized != from_bool:
                raise ValueError("decision and approved disagree.")
            normalized = from_bool
        self.decision = normalized  # type: ignore[assignment]
        actor = self.human_actor.strip()
        if not actor:
            raise ValueError("human_actor cannot be blank.")
        lowered = actor.casefold().replace("-", "_").replace(" ", "_")
        forbidden = {"agent", "boss", "inventory", "accounting", "facilities", "customer_service", "assistant", "system"}
        if lowered in forbidden or lowered.startswith("agent_"):
            raise ValueError("An agent or system identity cannot approve a proposal.")
        self.human_actor = actor
        return self


class ApprovalResponse(BaseModel):
    approval_id: str
    ticket_id: int
    status: str
    decision: str
    database_changed: bool
    message: str
    result: dict[str, object] | None = None


class CashResponse(BaseModel):
    checking_balance: float
    available_cash: float
    cash_accounts: list[dict[str, object]]


class ResetRequest(BaseModel):
    """Reset requires an explicit confirmation in the HTTP request body."""

    confirm: bool = False


class ResetResponse(BaseModel):
    status: str
    message: str
    cleared_approvals: int = 0
