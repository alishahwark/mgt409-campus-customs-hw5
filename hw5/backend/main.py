"""FastAPI routes for the Campus Customs agent team and dashboard."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
import threading
from typing import Any, Callable
from uuid import uuid4

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# Keep ``uvicorn main:app`` working when launched from backend/ while retaining
# normal package imports when the app is imported from the project root.
if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[1]
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))
    from backend.audit import AUDIT_PATH, append_audit_entry
    from backend.mcp_client import MCPToolClient
    from backend.models import (
        ActionProposal, ApprovalDecisionRequest, ApprovalResponse, CashResponse, CreateTicketRequest,
        Dependency, Finding, PendingApproval, ResetRequest, ResetResponse, RunTicketRequest,
        TeamRunSummary, TicketRunResponse, TicketSummary, TicketsResponse,
    )
    from backend.team import TeamRuntime
else:
    from .audit import AUDIT_PATH, append_audit_entry
    from .mcp_client import MCPToolClient
    from .models import (
        ActionProposal, ApprovalDecisionRequest, ApprovalResponse, CashResponse, CreateTicketRequest,
        Dependency, Finding, PendingApproval, ResetRequest, ResetResponse, RunTicketRequest,
        TeamRunSummary, TicketRunResponse, TicketSummary, TicketsResponse,
    )
    from .team import TeamRuntime


MCP_CLIENT_FACTORY: Callable[[], MCPToolClient] = MCPToolClient
TEAM_RUNTIME_FACTORY: Callable[[], TeamRuntime] = TeamRuntime


@dataclass
class PendingApprovalState:
    approval_id: str
    ticket_id: int
    proposal: ActionProposal
    status: str = "pending"


app = FastAPI(title="Campus Customs API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATE_LOCK = threading.Lock()
_RUNNING_TICKETS: set[int] = set()
_PENDING_APPROVALS: dict[str, PendingApprovalState] = {}
_LAST_RUNS: dict[int, TicketRunResponse] = {}
_PAYMENT_IN_PROGRESS = False
_RESET_IN_PROGRESS = False
_CREATING_TICKETS = 0


def _approval_view(state: PendingApprovalState) -> PendingApproval:
    proposal = state.proposal
    return PendingApproval(
        approval_id=state.approval_id, ticket_id=state.ticket_id,
        action=proposal.action, action_type=proposal.action_type,
        details=proposal.details, amount=proposal.amount,
        account=proposal.account, reference_type=proposal.reference_type,
        reference_id=proposal.reference_id, status=state.status,  # type: ignore[arg-type]
    )


def _api_audit(*, ticket_id: int, action: str, arguments: Any = None,
               result: Any = None, status: str = "in_progress",
               approval_required: bool = False,
               stop_reason: str | None = None) -> None:
    append_audit_entry(
        ticket_id=ticket_id, agent_name="api", action=action,
        arguments=arguments, result=result, status=status,
        approval_required=approval_required, stop_reason=stop_reason,
    )


async def _mcp_call(tool_name: str, arguments: dict[str, Any], *,
                    raise_on_tool_error: bool = True) -> dict[str, Any]:
    """Call one MCP tool; backend code never opens or queries SQLite."""
    try:
        async with MCP_CLIENT_FACTORY() as client:
            result = await client.call(tool_name, arguments)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MCP call failed: {exc}") from exc
    if result.get("ok") is False and raise_on_tool_error:
        raise HTTPException(status_code=502, detail=result.get("error", f"MCP tool {tool_name} failed."))
    return result


async def _ticket_from_mcp(ticket_id: int) -> dict[str, Any]:
    if ticket_id < 1:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} was not found.")
    result = await _mcp_call("get_ticket_details", {"ticket_id": ticket_id}, raise_on_tool_error=False)
    if result.get("code") == "not_found":
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} was not found.")
    if result.get("ok") is False:
        raise HTTPException(status_code=502, detail=_error_detail(result))
    if not isinstance(result.get("ticket"), dict):
        raise HTTPException(status_code=502, detail="MCP returned no ticket data.")
    return result


def _ticket_summary(result: dict[str, Any]) -> TicketSummary:
    ticket = result["ticket"]
    return TicketSummary(
        id=int(ticket["id"]), type=str(ticket["type"]),
        requester=str(ticket["requester"]), subject=str(ticket["subject"]),
        description=ticket.get("notes"), status=str(ticket["status"]),
        sku=ticket.get("sku"), size=ticket.get("size"),
        quantity=ticket.get("qty"), lease_id=ticket.get("lease_id"),
        invoice_id=ticket.get("invoice_id"), created_at=ticket.get("created_at"),
        resolution=result.get("resolution"),
    )


def _register_pending_approvals(summary: TeamRunSummary, ticket: dict[str, Any]) -> list[PendingApproval]:
    pending: list[PendingApproval] = []
    seen_payments: set[tuple[str, int, float, str]] = set()
    for proposal in summary.proposed_actions:
        # Only a concrete payment can be executed by /api/approvals. Drafts,
        # investigations, and unpriced purchases remain review requirements in
        # the run result; they must never appear as payable approval buttons.
        if (
            not proposal.requires_human_approval
            or proposal.action_type != "payment"
            or proposal.amount is None
            or proposal.reference_type not in {"invoice", "lease"}
            or proposal.reference_id is None
        ):
            continue
        declared_reference = ticket.get("invoice_id") if proposal.reference_type == "invoice" else ticket.get("lease_id")
        if declared_reference is None or int(declared_reference) != proposal.reference_id:
            continue
        key = (proposal.reference_type, proposal.reference_id, proposal.amount,
               proposal.account or "checking")
        if key in seen_payments:
            continue
        seen_payments.add(key)
        approval_id = f"approval-{uuid4().hex}"
        state = PendingApprovalState(approval_id, summary.ticket_id, proposal)
        _PENDING_APPROVALS[approval_id] = state
        pending.append(_approval_view(state))
        _api_audit(ticket_id=summary.ticket_id, action="approval_requested",
                   arguments={"approval_id": approval_id, "reference_type": proposal.reference_type,
                              "reference_id": proposal.reference_id},
                   result={"amount": proposal.amount, "account": proposal.account or "checking",
                           "purpose": proposal.details},
                   status="needs_approval", approval_required=True)
    return pending


def _error_detail(result: dict[str, Any]) -> str:
    return str(result.get("error", "MCP operation failed."))


async def _complete_operational_ticket(
    ticket_id: int, summary: TeamRunSummary, runtime: TeamRuntime
) -> TeamRunSummary:
    """Use actual specialist turns plus fresh MCP checks for internal closure."""
    if summary.stop_reason is not None:
        return summary
    turns = getattr(getattr(runtime, "context", None), "turns", [])
    boss = next((turn for turn in reversed(turns) if turn.assigned_agent == "boss"), None)
    service = next((turn for turn in reversed(turns) if turn.assigned_agent == "customer_service"), None)
    required_specialists = {"inventory", "customer_service"}
    if ticket_id == 103:
        required_specialists.add("accounting")
    participated = {turn.assigned_agent for turn in turns}
    expected_decision = (
        "unavailable_request_alternative" if ticket_id == 101
        else "decline_unfulfillable_bulk_request"
    )
    active_commitments = [
        item for item in (boss.proposed_actions if boss is not None else [])
        if item.action_type in {"payment", "purchase_order", "restock", "external_contact"}
        and not item.completed
    ]
    if (boss is None or boss.resolution_decision != expected_decision
            or service is None or not service.customer_draft
            or not required_specialists.issubset(participated)
            or active_commitments):
        if summary.status != "completed":
            return summary
        summary.status = "needs_approval" if active_commitments else "blocked"
        summary.stop_reason = "internal_decision_or_draft_incomplete"
        summary.dependencies.append(Dependency(
            description="A Boss final decision, actual Inventory/Accounting/Customer Service work, "
                        "a complete Customer Service draft, and no active purchase/payment/contact "
                        "proposal are required for internal desk closure.",
            blocking=True,
        ))
        return summary

    if ticket_id == 101:
        request = await _mcp_call(
            "record_replenishment_review_request", {"ticket_id": ticket_id},
            raise_on_tool_error=False,
        )
        _api_audit(ticket_id=ticket_id, action="internal_replenishment_review",
                   arguments={"tool": "record_replenishment_review_request"},
                   result=request, status="completed" if request.get("ok") else "blocked")
        if request.get("ok") is not True:
            summary.status = "blocked"
            summary.stop_reason = "replenishment_review_validation_failed"
            summary.final_reasoning += f" Internal review was not recorded: {_error_detail(request)}"
            return summary

    if summary.status != "completed":
        if ticket_id == 101:
            summary.final_reasoning += (
                " The internal review request is now recorded. A follow-up agent "
                "run must independently verify it before desk closure."
            )
        return summary

    closure = await _mcp_call(
        "close_operational_ticket",
        {"ticket_id": ticket_id, "decision": expected_decision,
         "customer_draft": service.customer_draft,
         "boss_reasoning": boss.final_reasoning},
        raise_on_tool_error=False,
    )
    _api_audit(ticket_id=ticket_id, action="operational_ticket_closure",
               arguments={"tool": "close_operational_ticket", "decision": expected_decision},
               result=closure, status="completed" if closure.get("ok") else "blocked")
    if closure.get("ok") is not True:
        summary.status = "blocked"
        summary.stop_reason = "operational_closure_validation_failed"
        summary.final_reasoning += f" Database ticket remains open: {_error_detail(closure)}"
        return summary
    summary.findings.append(Finding(
        fact="Internal desk decision and unsent Customer Service draft were recorded; "
             "no physical fulfillment or customer contact was represented.",
        source="close_operational_ticket",
    ))
    summary.final_reasoning += (
        " The internal desk ticket is resolved with a recorded final decision "
        "and unsent draft; fulfillment and external communication remain unconfirmed."
    )
    return summary


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/tickets", response_model=TicketsResponse)
async def get_tickets() -> TicketsResponse:
    """Return all tickets and their MCP-verified current statuses."""
    result = await _mcp_call("list_tickets", {})
    return TicketsResponse(
        tickets=[_ticket_summary({"ticket": row, "resolution": row.get("resolution")})
                 for row in result.get("tickets", [])],
        shop_date=result.get("shop_date"),
    )


@app.post("/api/tickets", response_model=TicketSummary, status_code=201)
async def create_ticket(request: CreateTicketRequest) -> TicketSummary:
    """Create one open ticket through MCP; never start agents automatically."""
    global _CREATING_TICKETS
    with _STATE_LOCK:
        if _RESET_IN_PROGRESS:
            raise HTTPException(status_code=409, detail="A database reset is in progress.")
        _CREATING_TICKETS += 1
    try:
        result = await _mcp_call(
            "create_ticket", {"subject": request.subject, "description": request.description},
            raise_on_tool_error=False,
        )
        if result.get("ok") is not True:
            raise HTTPException(status_code=409, detail=_error_detail(result))
        summary = _ticket_summary(result)
        _api_audit(ticket_id=summary.id, action="ticket_created",
                   arguments={"subject": summary.subject},
                   result={"status": summary.status, "source": "create_ticket"},
                   status="completed")
        return summary
    finally:
        with _STATE_LOCK:
            _CREATING_TICKETS -= 1


@app.post("/api/tickets/{ticket_id}/run", response_model=TicketRunResponse)
async def run_ticket(ticket_id: int, request: RunTicketRequest | None = Body(default=None)) -> TicketRunResponse:
    """Run one bounded Boss-led workflow, never executing proposed actions."""
    ticket = (await _ticket_from_mcp(ticket_id))["ticket"]
    if ticket.get("status") != "open":
        raise HTTPException(status_code=409, detail="Only open tickets can be run.")
    with _STATE_LOCK:
        if _RESET_IN_PROGRESS:
            raise HTTPException(status_code=409, detail="A database reset is in progress.")
        if ticket_id in _RUNNING_TICKETS:
            raise HTTPException(status_code=409, detail=f"Ticket {ticket_id} is already running.")
        _RUNNING_TICKETS.add(ticket_id)
    task = request.task if request is not None else None
    if not task and ticket_id == 101:
        task = (
            "Coordinate Inventory, Accounting if needed, and Customer Service for Ticket 101. "
            "Verify the linked paid invoice, zero size-S stock, vendor and lead time. "
            "Make a final internal unavailability/alternative-request decision, not a purchase "
            "or delivery promise. Customer Service must provide a complete unsent draft in "
            "customer_draft. If all internal desk work is complete, set the structured "
            "resolution_decision to unavailable_request_alternative and status completed."
        )
    elif not task and ticket_id == 103:
        task = (
            "Coordinate Inventory, Accounting, and Customer Service for Ticket 103. "
            "Verify 8 of 20 hoodies, the 12-unit shortage, pricing and margin, and absence "
            "of a verified supplier. Do not quote a discount or promise 20 units. Make a "
            "final internal decision to decline the infeasible 20-unit/discount request now. "
            "Customer Service must provide a complete unsent draft in customer_draft. "
            "If all internal desk work is complete, set resolution_decision to "
            "decline_unfulfillable_bulk_request and status completed."
        )
    elif not task and ticket_id not in {101, 102, 103}:
        task = (
            "Analyze this dashboard-created ticket using only MCP-verified facts. "
            "Its requester and type are placeholders, not verified business relationships; "
            "SKU, size, quantity, invoice, and lease links may be absent. Delegate "
            "appropriate bounded tasks to specialists, preserve missing facts as "
            "dependencies, and prepare only unsent drafts or proposals. Do not "
            "invent links, prices, stock, commitments, payments, or fulfillment. "
            "Do not claim the database ticket is resolved: no generic evidence-gated "
            "closure operation exists for dashboard-created tickets."
        )
    _api_audit(ticket_id=ticket_id, action="api_run_requested", arguments={"task": task}, result={"status": "started"})
    try:
        runtime = TEAM_RUNTIME_FACTORY()
        summary = await runtime.run_ticket(ticket_id, task)
        if not isinstance(summary, TeamRunSummary):
            summary = TeamRunSummary.model_validate(summary)
        if ticket_id == 102 and summary.status == "completed" and summary.stop_reason is None:
            closure = await _mcp_call(
                "resolve_paid_rent_ticket", {"ticket_id": ticket_id},
                raise_on_tool_error=False,
            )
            if closure.get("ok") is True:
                if closure.get("changed"):
                    _api_audit(ticket_id=ticket_id, action="ticket_status_resolved",
                               arguments={"tool": "resolve_paid_rent_ticket"},
                               result=closure, status="completed")
            else:
                summary.status = "blocked"
                summary.stop_reason = "resolution_verification_failed"
                summary.final_reasoning += f" Database status remains open: {_error_detail(closure)}"
                _api_audit(ticket_id=ticket_id, action="ticket_resolution_blocked",
                           arguments={"tool": "resolve_paid_rent_ticket"},
                           result=closure, status="blocked",
                           stop_reason=summary.stop_reason)
        if ticket_id in {101, 103}:
            summary = await _complete_operational_ticket(ticket_id, summary, runtime)
            evidence = await _mcp_call(
                "assess_ticket_resolution", {"ticket_id": ticket_id}
            )
            _api_audit(ticket_id=ticket_id, action="ticket_resolution_evidence",
                       arguments={"tool": "assess_ticket_resolution"},
                       result=evidence, status="completed" if evidence.get("can_close") else "blocked")
            if summary.status == "completed" and evidence.get("can_close") is not True:
                summary.status = "blocked"
                summary.stop_reason = "completion_evidence_missing"
                summary.dependencies.extend(
                    Dependency(description=str(item), blocking=True)
                    for item in evidence.get("missing_evidence", [])
                )
                summary.final_reasoning += " Ticket remains open: independent MCP completion evidence is missing."
        unlinked_payments = [
            proposal for proposal in summary.proposed_actions
            if proposal.action_type == "payment" and (
                proposal.reference_type not in {"invoice", "lease"}
                or proposal.reference_id is None
                or ticket.get("invoice_id" if proposal.reference_type == "invoice" else "lease_id") != proposal.reference_id
            )
        ]
        if unlinked_payments:
            summary.status = "blocked"
            summary.stop_reason = "unverified_payment_reference"
            summary.dependencies.append(Dependency(
                description="Payment proposal has no matching declared ticket invoice or lease link; it cannot be approved or executed.",
                owner="accounting", blocking=True,
            ))
        if ticket_id not in {101, 102, 103} and summary.status == "completed":
            summary.final_reasoning += " Agent review is complete, but the database ticket remains open; no generic closure was performed."
        pending = _register_pending_approvals(summary, ticket)
        response = TicketRunResponse(**summary.model_dump(mode="json"), pending_approvals=pending)
        _LAST_RUNS[ticket_id] = response
        _api_audit(ticket_id=ticket_id, action="api_run_completed",
                   result={"status": response.status, "pending_approvals": len(pending)},
                   status=response.status, approval_required=bool(pending),
                   stop_reason=response.stop_reason)
        return response
    except HTTPException:
        raise
    except Exception as exc:
        _api_audit(ticket_id=ticket_id, action="api_run_failed", result={"error": str(exc)},
                   status="blocked", stop_reason="api_run_failure")
        raise HTTPException(status_code=500, detail=f"Ticket run failed: {exc}") from exc
    finally:
        with _STATE_LOCK:
            _RUNNING_TICKETS.discard(ticket_id)


@app.get("/api/events")
def get_events(
    limit: int = Query(default=50, ge=1, le=500),
    ticket_id: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """Return recent activity, optionally filtered by ticket before limiting."""
    try:
        records = json.loads(AUDIT_PATH.read_text()) if AUDIT_PATH.exists() else []
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Audit trail could not be read: {exc}") from exc
    if not isinstance(records, list):
        raise HTTPException(status_code=500, detail="Audit trail must contain a JSON array.")
    matching = (
        records if ticket_id is None
        else [record for record in records if isinstance(record, dict) and record.get("ticket_id") == ticket_id]
    )
    events: list[dict[str, Any]] = []
    for record in matching[-limit:]:
        if isinstance(record, dict):
            event = dict(record)
            event.setdefault("message", event.get("action", "activity"))
            events.append(event)
    return {"events": events, "limit": limit, "count": len(events)}


async def _payment_reference(state: PendingApprovalState) -> tuple[str, int, float, str]:
    proposal = state.proposal
    if proposal.action_type != "payment":
        raise HTTPException(status_code=409, detail="Only payment proposals can be executed by the available database schema; purchase proposals require a later authorized workflow.")
    if proposal.amount is None:
        raise HTTPException(status_code=409, detail="The payment proposal has no verified amount.")
    kind, reference_id = proposal.reference_type, proposal.reference_id
    if kind not in {"invoice", "lease"} or reference_id is None:
        details = await _ticket_from_mcp(state.ticket_id)
        ticket = details["ticket"]
        if ticket.get("invoice_id") is not None:
            kind, reference_id = "invoice", int(ticket["invoice_id"])
        elif ticket.get("lease_id") is not None:
            kind, reference_id = "lease", int(ticket["lease_id"])
    if kind not in {"invoice", "lease"} or reference_id is None:
        raise HTTPException(status_code=409, detail="The proposal is not linked to a verified invoice or lease.")
    ticket = (await _ticket_from_mcp(state.ticket_id))["ticket"]
    declared_reference = ticket.get("invoice_id" if kind == "invoice" else "lease_id")
    if declared_reference is None or int(declared_reference) != int(reference_id):
        raise HTTPException(status_code=409, detail="The payment reference is not declared on this ticket.")
    # Tickets use a lease reference; payments.kind records the corresponding
    # cash movement as "rent" in the actual payments table.
    payment_kind = "rent" if kind == "lease" else kind
    return payment_kind, int(reference_id), float(proposal.amount), proposal.account or "checking"


async def _recheck_payment(kind: str, reference_id: int, amount: float, account: str) -> None:
    cash = await _mcp_call("get_cash_position", {})
    account_row = next((row for row in cash.get("cash_accounts", [])
                        if isinstance(row, dict) and row.get("name") == account), None)
    if account_row is None:
        raise HTTPException(status_code=409, detail=f"Cash account {account!r} was not found.")
    balance = float(account_row["balance"])
    if amount > balance + 1e-9:
        raise HTTPException(status_code=409, detail=f"Insufficient cash: {account} has {balance}, but {amount} is required.")
    if kind == "invoice":
        history = await _mcp_call("get_payment_history", {"invoice_id": reference_id})
        invoice = history.get("invoice")
        if not isinstance(invoice, dict):
            raise HTTPException(status_code=409, detail="The invoice no longer exists.")
        if invoice.get("status") == "paid":
            raise HTTPException(status_code=409, detail="The invoice is already paid.")
        remaining = float(invoice["amount"]) - float(history.get("recorded_payment_total", 0))
    else:
        lease = await _mcp_call("check_lease_and_rent", {"lease_id": reference_id})
        remaining = float(lease["rent_amount"]) - float(lease.get("recorded_payment_total", 0))
    if remaining <= 0:
        raise HTTPException(status_code=409, detail="The obligation is already fully paid.")
    if amount > remaining + 1e-9:
        raise HTTPException(status_code=409, detail="The proposal exceeds the remaining obligation.")


@app.post("/api/approvals/{approval_id}", response_model=ApprovalResponse)
async def decide_approval(approval_id: str, request: ApprovalDecisionRequest) -> ApprovalResponse:
    """Apply or reject one explicitly human-triggered pending proposal."""
    global _PAYMENT_IN_PROGRESS
    with _STATE_LOCK:
        state = _PENDING_APPROVALS.get(approval_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Approval proposal was not found.")
        if state.status != "pending":
            raise HTTPException(status_code=409, detail=f"Approval is already {state.status}.")
        if request.decision == "reject":
            state.status = "rejected"
            _api_audit(ticket_id=state.ticket_id, action="approval_rejected",
                       arguments={"approval_id": approval_id, "human_actor": request.human_actor},
                       result={"database_changed": False}, status="blocked", approval_required=True)
            return ApprovalResponse(approval_id=approval_id, ticket_id=state.ticket_id,
                                    status="rejected", decision="reject", database_changed=False,
                                    message="Proposal rejected; the database was not changed.")
        if _PAYMENT_IN_PROGRESS:
            raise HTTPException(status_code=409, detail="Another payment is already executing.")
        state.status = "executing"
        _PAYMENT_IN_PROGRESS = True
    try:
        kind, reference_id, amount, account = await _payment_reference(state)
        await _recheck_payment(kind, reference_id, amount, account)
        result = await _mcp_call(
            "execute_approved_payment",
            {"approval_id": approval_id, "human_approved_by": request.human_actor,
             "kind": kind, "reference_id": reference_id, "amount": amount, "account": account},
            raise_on_tool_error=False,
        )
        if result.get("ok") is not True:
            raise HTTPException(status_code=409, detail=_error_detail(result))
        with _STATE_LOCK:
            state.status = "executed"
        _api_audit(ticket_id=state.ticket_id, action="approval_executed",
                   arguments={"approval_id": approval_id, "human_actor": request.human_actor},
                   result=result, status="completed", approval_required=True)
        return ApprovalResponse(approval_id=approval_id, ticket_id=state.ticket_id,
                                status="executed", decision="approve", database_changed=True,
                                message="Approved payment executed atomically through MCP.", result=result)
    except HTTPException as exc:
        with _STATE_LOCK:
            state.status = "failed"
        _api_audit(ticket_id=state.ticket_id, action="approval_failed",
                   arguments={"approval_id": approval_id}, result={"error": str(exc.detail)},
                   status="blocked", approval_required=True, stop_reason="approval_execution_failed")
        raise
    except Exception as exc:
        with _STATE_LOCK:
            state.status = "failed"
        _api_audit(ticket_id=state.ticket_id, action="approval_failed",
                   arguments={"approval_id": approval_id}, result={"error": str(exc)},
                   status="blocked", approval_required=True, stop_reason="approval_execution_failed")
        raise HTTPException(status_code=500, detail=f"Approval execution failed: {exc}") from exc
    finally:
        with _STATE_LOCK:
            _PAYMENT_IN_PROGRESS = False


@app.get("/api/cash", response_model=CashResponse)
async def get_cash() -> CashResponse:
    """Read the current checking balance from the working database through MCP."""
    result = await _mcp_call("get_cash_position", {})
    accounts = result.get("cash_accounts", [])
    checking = next((row for row in accounts if isinstance(row, dict) and row.get("name") == "checking"), None)
    if checking is None:
        raise HTTPException(status_code=502, detail="The checking cash account was not found.")
    return CashResponse(checking_balance=float(checking["balance"]),
                        available_cash=float(result.get("available_cash", checking["balance"])),
                        cash_accounts=accounts)


@app.post("/api/reset", response_model=ResetResponse)
async def reset_database(request: ResetRequest) -> ResetResponse:
    """Explicitly reset the working database through the MCP server only."""
    global _RESET_IN_PROGRESS
    if request.confirm is not True:
        raise HTTPException(status_code=400, detail="Set confirm=true to explicitly request a reset.")
    with _STATE_LOCK:
        if _RUNNING_TICKETS or _PAYMENT_IN_PROGRESS or _RESET_IN_PROGRESS or _CREATING_TICKETS:
            raise HTTPException(status_code=409, detail="Cannot reset while a ticket run, ticket creation, payment, or reset is executing.")
        _RESET_IN_PROGRESS = True
    try:
        result = await _mcp_call("reset_working_database", {"confirm": True}, raise_on_tool_error=False)
        if result.get("ok") is not True:
            raise HTTPException(status_code=409, detail=_error_detail(result))
        with _STATE_LOCK:
            cleared = len(_PENDING_APPROVALS)
            _PENDING_APPROVALS.clear()
            _LAST_RUNS.clear()
        _api_audit(ticket_id=0, action="database_reset", arguments={"confirm": True},
                   result={"database_changed": True}, status="completed")
        return ResetResponse(status="reset",
                             message="Working database restored from the untouched original; audit history preserved.",
                             cleared_approvals=cleared)
    finally:
        with _STATE_LOCK:
            _RESET_IN_PROGRESS = False
