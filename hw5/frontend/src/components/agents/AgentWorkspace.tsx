import { Boxes, BriefcaseBusiness, Calculator, Headset, Wrench, type LucideIcon } from 'lucide-react';
import type { AgentName, AuditEvent } from '../../api/client';
import { eventTime } from '../../api/client';
import { Status, type DisplayStatus } from '../common/Status';

const AGENTS: { name: AgentName; label: string; role: string; icon: LucideIcon }[] = [
  { name: 'boss', label: 'Boss', role: 'Coordinator', icon: BriefcaseBusiness },
  { name: 'inventory', label: 'Inventory', role: 'Stock & vendors', icon: Boxes },
  { name: 'accounting', label: 'Accounting', role: 'Cash & pricing', icon: Calculator },
  { name: 'facilities', label: 'Facilities', role: 'Lease & rent', icon: Wrench },
  { name: 'customer_service', label: 'Customer Service', role: 'Customer drafts', icon: Headset },
];

function agentState(event: AuditEvent | undefined, running: boolean): DisplayStatus {
  if (!running || !event) return 'idle';
  if (event.action === 'agent_failure' || event.status === 'blocked') return 'blocked';
  if (event.status === 'needs_approval') return 'waiting';
  if (event.action === 'agent_result' || event.status === 'completed') return 'completed';
  if (running && (event.action === 'agent_start' || event.action === 'mcp_tool_call' || event.action === 'delegation')) return 'running';
  return 'idle';
}

export function AgentWorkspace({ events, selectedId, running }: { events: AuditEvent[]; selectedId: number | null; running: boolean }) {
  const relevant = selectedId === null ? [] : events.filter(event => event.ticket_id === selectedId);
  const lastStart = relevant.findLastIndex(event => event.action === 'api_run_requested');
  const current = lastStart >= 0 ? relevant.slice(lastStart) : relevant;
  const delegations = relevant.filter(event => event.action === 'delegation');
  return <section className="section agent-section" aria-labelledby="agents-heading">
    <div className="section-heading"><div><span className="eyebrow">03 / Team system</span><h2 id="agents-heading">Agent workspace</h2></div><span className="section-note">{selectedId ? `Current status · Ticket #${selectedId}` : 'Select a ticket'}</span></div>
    <div className="agent-grid">{AGENTS.map(({ name, label, role, icon: Icon }) => {
      const last = [...relevant].reverse().find(event => event.agent_name === name);
      const activeEvent = running ? [...current].reverse().find(event => event.agent_name === name) : undefined;
      const state = agentState(activeEvent, running);
      const displayedEvent = activeEvent ?? last;
      const action = activeEvent ? `Current · ${activeEvent.action.replaceAll('_', ' ')}`
        : last ? `History · ${last.action.replaceAll('_', ' ')}` : 'No recorded participation';
      return <article key={name} className={`agent-module${name === 'boss' ? ' agent-module--boss' : ''}${state === 'running' ? ' agent-module--working' : ''}`}>
        <div className="agent-module__top"><span className="agent-icon"><Icon size={17} strokeWidth={1.7} aria-hidden="true" /></span><Status value={state} /></div>
        <div><h3>{label}</h3><p>{role}</p></div>
        <div className="agent-module__action"><span>{action}</span>{displayedEvent ? <time className="mono" dateTime={displayedEvent.timestamp}>{eventTime(displayedEvent.timestamp)}</time> : null}</div>
      </article>;
    })}</div>
    {delegations.length > 0 ? <div className="delegations"><span className="eyebrow">Recorded handoffs</span><div className="delegations__list">{delegations.map((event, index) => {
      const args = event.arguments && typeof event.arguments === 'object' ? event.arguments as Record<string, unknown> : {};
      return <span className="delegation-path" key={`${event.timestamp}-${index}`}><span>{event.agent_name.replaceAll('_', ' ')}</span><span aria-hidden="true">→</span><strong>{typeof args.target_agent === 'string' ? args.target_agent.replaceAll('_', ' ') : 'Agent'}</strong></span>;
    })}</div></div> : null}
  </section>;
}
