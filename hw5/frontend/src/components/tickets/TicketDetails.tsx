import { ArrowRight, Check, Play } from 'lucide-react';
import type { Ticket, TicketRunResponse } from '../../api/client';
import { money } from '../../api/client';
import { Status, type DisplayStatus } from '../common/Status';
import { ticketDisplayStatus } from './TicketTable';

export function TicketDetails({ ticket, run, running, onRun, onApprovals }: {
  ticket: Ticket | null; run: TicketRunResponse | undefined; running: boolean;
  onRun: () => void; onApprovals: () => void;
}) {
  if (!ticket) return <section className="section detail-section"><span className="eyebrow">02 / Ticket detail</span><p className="empty-line">Select a ticket to inspect its details and agent findings.</p></section>;
  const status = ticketDisplayStatus(ticket, run, running);
  const decisionText = ticket.resolution?.decision === 'unavailable_request_alternative'
    ? 'Item unavailable · alternative requested'
    : 'Requested bulk quantity and discount not offered';
  const pending = run?.pending_approvals.filter(item => item.status === 'pending') ?? [];
  const runStatus: DisplayStatus = !run ? 'idle' : run.status === 'completed' ? 'completed'
    : run.status === 'needs_approval' ? 'awaiting'
    : run.status === 'blocked' || run.status === 'stopped' ? 'blocked'
    : run.status === 'in_progress' ? 'running' : 'waiting';
  const primaryLabel = ticket.status === 'resolved' ? 'Desk Resolved' : running ? 'Running...' : pending.length > 0 ? 'Review Approval' : run ? 'View Results' : 'Run Ticket';
  const primaryAction = () => {
    if (pending.length > 0) onApprovals();
    else if (run) document.querySelector('.report')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    else onRun();
  };
  return <section className="section detail-section" aria-labelledby="detail-heading">
    <div className="section-heading"><div><span className="eyebrow">02 / Ticket detail · <span className="mono">#{ticket.id}</span></span><h2 id="detail-heading">{ticket.subject}</h2></div><Status value={status} /></div>
    <div className="detail-facts"><div><span>Requested by</span><strong>{ticket.requester}</strong></div><div><span>Type</span><strong>{ticket.type.replaceAll('_', ' ')}</strong></div>{ticket.sku ? <div><span>Product</span><strong className="mono">{ticket.sku}{ticket.size ? ` / ${ticket.size}` : ''}</strong></div> : null}{ticket.quantity !== null ? <div><span>Quantity</span><strong className="mono">{ticket.quantity}</strong></div> : null}{ticket.lease_id !== null ? <div><span>Lease</span><strong className="mono">#{ticket.lease_id}</strong></div> : null}{ticket.invoice_id !== null ? <div><span>Invoice</span><strong className="mono">#{ticket.invoice_id}</strong></div> : null}</div>
    <p className="detail-description">{ticket.description || 'No description provided.'}</p>
    {ticket.resolution ? <div className="resolution-record" aria-label="Recorded internal desk resolution">
      <div className="resolution-record__head"><span className="eyebrow">Recorded desk decision</span><span className="mono">{ticket.resolution.shop_date}</span></div>
      <strong>{decisionText}</strong>
      <p>Stock at decision: {ticket.resolution.stock_at_decision} · Shortage: {ticket.resolution.shortage_at_decision}. Physical fulfillment not recorded. Customer message not sent.</p>
      <div className="resolution-record__draft"><span className="eyebrow">Customer Service draft · unsent</span><p>{ticket.resolution.customer_draft}</p></div>
    </div> : null}
    <div className="detail-actions"><button type="button" className="button button--black" onClick={primaryAction} disabled={running || ticket.status === 'resolved'}>{ticket.status === 'resolved' ? <Check size={15} /> : running ? <span className="spinner" aria-hidden="true" /> : pending.length > 0 || run ? <ArrowRight size={15} /> : <Play size={14} fill="currentColor" />} {primaryLabel}</button>{run && !running && ticket.status !== 'resolved' ? <button type="button" className="button button--outline" onClick={onRun}>Run again <ArrowRight size={15} /></button> : null}</div>
    {run ? <div className="report" aria-label="Agent run result">
      <div className="report__head"><span className="eyebrow">Resolution report</span><span className="mono report__meta">{run.iterations} iterations · {run.delegations} delegations</span></div>
      <div className="report__grid">
        <div><span className="report__label">Run outcome</span><p><Status value={runStatus}>{run.status.replaceAll('_', ' ')}</Status></p><p className="report__reason">{run.final_reasoning}</p><p className="quiet">Database ticket status: {ticket.status.replaceAll('_', ' ')}</p></div>
        <div><span className="report__label">Agent contributions</span>{run.findings.length ? <ul>{run.findings.map((finding, index) => <li key={`${finding.source}-${index}`}>{finding.fact}<small>{finding.source}</small></li>)}</ul> : <p className="quiet">No verified findings returned.</p>}</div>
        <div><span className="report__label">Completed actions</span>{run.proposed_actions.filter(action => action.completed).length ? <ul>{run.proposed_actions.filter(action => action.completed).map((action, index) => <li key={index}>{action.action}</li>)}</ul> : <p className="quiet">No completed actions returned.</p>}</div>
        <div><span className="report__label">Pending actions</span>{run.proposed_actions.filter(action => !action.completed).length ? <ul>{run.proposed_actions.filter(action => !action.completed).map((action, index) => <li key={index}>{action.action}{action.amount !== null ? ` · ${money(action.amount)}` : ''}<small>{action.details}</small></li>)}</ul> : <p className="quiet">No pending actions returned.</p>}</div>
      </div>
      {run.dependencies.filter(item => item.blocking && !item.resolved).length ? <div className="report__footer"><span className="report__label">Open dependencies</span>{run.dependencies.filter(item => item.blocking && !item.resolved).map((item, index) => <p key={index}>{item.description}</p>)}</div> : null}
      {run.stop_reason ? <div className="report__footer"><span className="report__label">Stop reason</span><p>{run.stop_reason}</p></div> : null}
    </div> : <div className="detail-hint"><span className="detail-hint__line" /><p>Agent findings and decisions will appear here after a run.</p></div>}
  </section>;
}
