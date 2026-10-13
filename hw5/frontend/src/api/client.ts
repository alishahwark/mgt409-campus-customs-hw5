/** Exact public shapes from backend/models.py and backend/main.py. */
export type AgentName = 'boss' | 'inventory' | 'accounting' | 'facilities' | 'customer_service';
export type TicketStatus = 'in_progress' | 'completed' | 'blocked' | 'needs_approval' | 'delegated' | 'stopped';
export type ActionType = 'read_only' | 'draft' | 'payment' | 'purchase_order' | 'restock' | 'external_contact' | 'other';

export interface Ticket {
  id: number;
  type: string;
  requester: string;
  subject: string;
  description: string | null;
  status: string;
  sku: string | null;
  size: string | null;
  quantity: number | null;
  lease_id: number | null;
  invoice_id: number | null;
  created_at: string | null;
  resolution: OperationalResolution | null;
}
export interface OperationalResolution {
  ticket_id: number;
  decision: 'unavailable_request_alternative' | 'decline_unfulfillable_bulk_request';
  customer_draft: string;
  shop_date: string;
  stock_at_decision: number;
  shortage_at_decision: number;
  communication_status: 'unsent_draft';
  fulfillment_status: 'not_fulfilled';
}
export interface TicketsResponse { tickets: Ticket[]; shop_date: string | null }
export interface CreateTicketInput { subject: string; description: string }
export interface CashResponse {
  checking_balance: number;
  available_cash: number;
  cash_accounts: Record<string, unknown>[];
}
export interface Finding { fact: string; source: string; verified: boolean }
export interface Dependency { description: string; owner: AgentName | null; blocking: boolean; resolved: boolean }
export interface ApprovalRequirement { action: string; reason: string; required: boolean }
export interface ActionProposal {
  action: string;
  owner: AgentName;
  action_type: ActionType;
  details: string;
  amount: number | null;
  available_cash: number | null;
  vendor_id: number | null;
  vendor_has_open_unpaid_invoices: boolean | null;
  reference_type: 'invoice' | 'lease' | 'purchase' | null;
  reference_id: number | null;
  account: string | null;
  requires_human_approval: boolean;
  completed: boolean;
}
export interface PendingApproval {
  approval_id: string;
  ticket_id: number;
  action: string;
  action_type: ActionType;
  details: string;
  amount: number | null;
  account: string | null;
  reference_type: string | null;
  reference_id: number | null;
  status: 'pending' | 'executing' | 'executed' | 'rejected' | 'failed';
}
export interface TicketRunResponse {
  ticket_id: number;
  status: TicketStatus;
  final_reasoning: string;
  findings: Finding[];
  proposed_actions: ActionProposal[];
  dependencies: Dependency[];
  approval_requirements: ApprovalRequirement[];
  pending_approvals: PendingApproval[];
  iterations: number;
  delegations: number;
  stop_reason: string | null;
}
export interface AuditEvent {
  timestamp: string;
  ticket_id: number;
  agent_name: string;
  action: string;
  arguments: unknown;
  result: unknown;
  iteration: number;
  delegation_depth: number;
  approval_required: boolean;
  status: string;
  stop_reason: string | null;
  message: string;
}
export interface EventsResponse { events: AuditEvent[]; limit: number; count: number }
export interface ApprovalResponse {
  approval_id: string;
  ticket_id: number;
  status: string;
  decision: string;
  database_changed: boolean;
  message: string;
  result: Record<string, unknown> | null;
}
export interface ResetResponse { status: string; message: string; cleared_approvals: number }

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = await response.json() as { detail?: string | { msg?: string }[] };
      if (typeof payload.detail === 'string') message = payload.detail;
      else if (Array.isArray(payload.detail)) message = payload.detail.map(item => item.msg).join('; ');
    } catch { /* Use the HTTP status if the response is not JSON. */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  tickets: () => request<TicketsResponse>('/api/tickets'),
  createTicket: (input: CreateTicketInput) => request<Ticket>('/api/tickets', {
    method: 'POST', body: JSON.stringify(input),
  }),
  events: (limit = 100, ticketId?: number) => request<EventsResponse>(`/api/events?limit=${limit}${ticketId === undefined ? '' : `&ticket_id=${ticketId}`}`),
  cash: () => request<CashResponse>('/api/cash'),
  run: (ticketId: number) => request<TicketRunResponse>(`/api/tickets/${ticketId}/run`, { method: 'POST', body: '{}' }),
  decide: (approvalId: string, decision: 'approve' | 'reject', humanActor: string) =>
    request<ApprovalResponse>(`/api/approvals/${encodeURIComponent(approvalId)}`, {
      method: 'POST', body: JSON.stringify({ decision, human_actor: humanActor }),
    }),
  reset: () => request<ResetResponse>('/api/reset', { method: 'POST', body: JSON.stringify({ confirm: true }) }),
};

export const money = (amount: number) => new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2,
}).format(amount);

export function eventTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('en-US', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date);
}
