import { ArrowUpRight, Play, Plus } from 'lucide-react';
import type { AuditEvent, Ticket, TicketRunResponse } from '../../api/client';
import { eventTime } from '../../api/client';
import { Status, type DisplayStatus } from '../common/Status';

export function ticketDisplayStatus(ticket: Ticket, run: TicketRunResponse | undefined, running: boolean): DisplayStatus {
  if (running) return 'running';
  if (ticket.status === 'resolved') return 'resolved';
  if (run?.pending_approvals.some(item => item.status === 'pending')) return 'awaiting';
  if (run?.status === 'blocked' || run?.status === 'stopped') return 'blocked';
  return 'open';
}

export function TicketTable({ tickets, selectedId, onSelect, onRun, onNewTicket, runs, runningIds, events, loading }: {
  tickets: Ticket[]; selectedId: number | null; onSelect: (id: number) => void; onRun: (id: number) => void;
  onNewTicket: () => void;
  runs: Record<number, TicketRunResponse>; runningIds: number[]; events: AuditEvent[]; loading: boolean;
}) {
  return <section className="section ticket-section" aria-labelledby="ticket-heading">
    <div className="section-heading"><div><span className="eyebrow">01 / Work queue</span><h2 id="ticket-heading">Tickets <span className="heading-count">{tickets.length}</span></h2></div><button type="button" className="button button--black" onClick={onNewTicket}><Plus size={14} aria-hidden="true" /> New Ticket</button></div>
    {loading && tickets.length === 0 ? <div className="skeleton-list" aria-label="Loading tickets"><div /><div /><div /></div> : null}
    {!loading && tickets.length === 0 ? <p className="empty-line">No tickets returned by the backend.</p> : null}
    {tickets.length > 0 ? <div className="ticket-table-wrap"><table className="ticket-table">
      <thead><tr><th scope="col">ID</th><th scope="col">Ticket</th><th scope="col">Status</th><th scope="col">Last activity</th><th scope="col" className="ticket-table__action-head">Action</th></tr></thead>
      <tbody>{tickets.map(ticket => {
        const running = runningIds.includes(ticket.id);
        const status = ticketDisplayStatus(ticket, runs[ticket.id], running);
        const last = [...events].reverse().find(event => event.ticket_id === ticket.id);
        return <tr key={ticket.id} className={selectedId === ticket.id ? 'ticket-row ticket-row--selected' : 'ticket-row'} onClick={() => onSelect(ticket.id)}>
          <td><button type="button" className="row-select ticket-id" onClick={event => { event.stopPropagation(); onSelect(ticket.id); }} aria-label={`Select ticket ${ticket.id}`}>#{ticket.id}</button></td>
          <td><button type="button" className="ticket-title-button" onClick={event => { event.stopPropagation(); onSelect(ticket.id); }}><strong>{ticket.subject}</strong><span>{ticket.description || ticket.requester}</span></button></td>
          <td><Status value={status} /></td>
          <td className="ticket-last mono">{last ? eventTime(last.timestamp) : '—'}</td>
          <td className="ticket-table__action"><button type="button" className="row-action" onClick={event => { event.stopPropagation(); if (running || status === 'resolved') return; if (runs[ticket.id]) onSelect(ticket.id); else onRun(ticket.id); }} disabled={running || status === 'resolved'} aria-label={runs[ticket.id] ? `View results for ticket ${ticket.id}` : `Run ticket ${ticket.id}`}>
            <span className="row-action__full">{running ? 'Running...' : status === 'resolved' ? 'Resolved' : status === 'awaiting' ? 'Review Approval' : runs[ticket.id] ? 'View Results' : 'Run Ticket'}</span><span className="row-action__compact">{running ? 'Running' : status === 'resolved' ? 'Resolved' : runs[ticket.id] ? 'View' : 'Run'}</span> {runs[ticket.id] ? <ArrowUpRight size={14} /> : !running && status !== 'resolved' ? <Play size={12} fill="currentColor" /> : null}
          </button></td>
        </tr>;
      })}</tbody>
    </table></div> : null}
  </section>;
}
