import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type { AuditEvent, Ticket } from '../../api/client';
import { eventTime } from '../../api/client';
import { Status, type DisplayStatus } from '../common/Status';

const EVENT_TYPES = ['All events', 'Agent', 'MCP tool', 'Delegation', 'Approval', 'API'] as const;

function eventType(event: AuditEvent): typeof EVENT_TYPES[number] {
  if (event.action.includes('mcp_')) return 'MCP tool';
  if (event.action.includes('delegation')) return 'Delegation';
  if (event.action.includes('approval')) return 'Approval';
  if (event.agent_name === 'api') return 'API';
  return 'Agent';
}
function eventStatus(event: AuditEvent): DisplayStatus {
  if (event.status === 'blocked' || event.action.includes('failure')) return 'blocked';
  if (event.status === 'needs_approval') return 'waiting';
  if (event.status === 'completed') return 'completed';
  return 'running';
}
function eventTool(event: AuditEvent): string {
  const args = event.arguments && typeof event.arguments === 'object' ? event.arguments as Record<string, unknown> : {};
  return typeof args.tool === 'string' ? args.tool : '—';
}

export function ActivityTimeline({ events, tickets, selectedId, onSelectTicket, running }: {
  events: AuditEvent[]; tickets: Ticket[]; selectedId: number | null; onSelectTicket: (id: number | null) => void; running: boolean;
}) {
  const [agent, setAgent] = useState('all');
  const [type, setType] = useState<typeof EVENT_TYPES[number]>('All events');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [newEvents, setNewEvents] = useState(false);
  const viewport = useRef<HTMLDivElement>(null);
  const previousCount = useRef(events.length);
  const agents = useMemo(() => [...new Set(events.map(event => event.agent_name))].sort(), [events]);
  const filtered = useMemo(() => events.map((event, index) => ({ event, index })).filter(({ event }) =>
    (selectedId === null || event.ticket_id === selectedId) &&
    (agent === 'all' || event.agent_name === agent) &&
    (type === 'All events' || eventType(event) === type)
  ).reverse(), [events, selectedId, agent, type]);

  useEffect(() => {
    if (events.length > previousCount.current && viewport.current && viewport.current.scrollTop > 60) setNewEvents(true);
    previousCount.current = events.length;
  }, [events]);

  useEffect(() => {
    setAgent('all');
    setType('All events');
    setExpanded(null);
    setNewEvents(false);
    viewport.current?.scrollTo({ top: 0 });
  }, [selectedId]);

  return <section className="section activity-section" aria-labelledby="activity-heading">
    <div className="section-heading"><div><span className="eyebrow">04 / Event log</span><h2 id="activity-heading">Agent activity</h2></div>{running ? <span className="live-indicator"><span className="status__dot" /> Live updates</span> : <span className="section-note">Recorded history · {filtered.length} events</span>}</div>
    <div className="activity-filters"><label>Ticket<select value={selectedId ?? 'all'} onChange={event => onSelectTicket(event.target.value === 'all' ? null : Number(event.target.value))}><option value="all">All tickets</option>{tickets.map(ticket => <option key={ticket.id} value={ticket.id}>#{ticket.id}</option>)}</select></label><label>Agent<select value={agent} onChange={event => setAgent(event.target.value)}><option value="all">All agents</option>{agents.map(name => <option key={name} value={name}>{name.replaceAll('_', ' ')}</option>)}</select></label><label>Type<select value={type} onChange={event => setType(event.target.value as typeof type)}>{EVENT_TYPES.map(value => <option key={value} value={value}>{value}</option>)}</select></label></div>
    {newEvents ? <button type="button" className="new-events" onClick={() => { viewport.current?.scrollTo({ top: 0, behavior: 'smooth' }); setNewEvents(false); }}>New events · Jump to latest</button> : null}
    <div className="activity-viewport" ref={viewport} onScroll={() => { if (viewport.current && viewport.current.scrollTop < 10) setNewEvents(false); }}>
      {filtered.length === 0 ? <div className="empty-state"><span className="eyebrow">No activity</span><p>{events.length ? 'No events match these filters.' : 'Select a ticket and run the agent team to begin.'}</p></div> : <div className="event-list">{filtered.map(({ event, index }) => {
        const key = `${event.timestamp}-${event.ticket_id}-${event.action}-${index}`;
        const open = expanded === key;
        return <article className="event" key={key}><button type="button" className="event__summary" aria-expanded={open} onClick={() => setExpanded(open ? null : key)}>
          <time className="mono" dateTime={event.timestamp}>{eventTime(event.timestamp)}</time><span className="event__agent">{event.agent_name.replaceAll('_', ' ')}</span><span className="event__action">{event.action.replaceAll('_', ' ')}</span><span className="event__tool mono">{eventTool(event)}</span><Status value={eventStatus(event)}>{event.status.replaceAll('_', ' ')}</Status>{open ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        </button>{open ? <div className="event__details"><div><span className="eyebrow">Ticket</span><strong className="mono">#{event.ticket_id}</strong></div><div><span className="eyebrow">Arguments</span><pre>{JSON.stringify(event.arguments, null, 2) ?? '—'}</pre></div><div><span className="eyebrow">Result</span><pre>{JSON.stringify(event.result, null, 2) ?? '—'}</pre></div><div><span className="eyebrow">Metadata</span><pre>{JSON.stringify({ iteration: event.iteration, delegation_depth: event.delegation_depth, approval_required: event.approval_required, stop_reason: event.stop_reason }, null, 2)}</pre></div></div> : null}</article>;
      })}</div>}
    </div>
  </section>;
}
