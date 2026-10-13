import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, ArrowUpRight, X } from 'lucide-react';
import { api, type AuditEvent, type CashResponse, type CreateTicketInput, type PendingApproval, type Ticket, type TicketRunResponse } from './api/client';
import { ActivityTimeline } from './components/agents/ActivityTimeline';
import { AgentWorkspace } from './components/agents/AgentWorkspace';
import { Modal } from './components/common/Modal';
import { Status } from './components/common/Status';
import { ApprovalQueue } from './components/finance/ApprovalQueue';
import { CashBalance } from './components/finance/CashBalance';
import { DecisionModal } from './components/finance/DecisionModal';
import { Header } from './components/layout/Header';
import { Sidebar, type Page } from './components/layout/Sidebar';
import { MetricsStrip } from './components/overview/MetricsStrip';
import { TicketDetails } from './components/tickets/TicketDetails';
import { TicketTable } from './components/tickets/TicketTable';
import { NewTicketModal } from './components/tickets/NewTicketModal';

const RUN_STORAGE_KEY = 'campus-customs-runs-v1';
function storedRuns(): Record<number, TicketRunResponse> {
  try {
    const raw = sessionStorage.getItem(RUN_STORAGE_KEY);
    return raw ? JSON.parse(raw) as Record<number, TicketRunResponse> : {};
  } catch { return {}; }
}

function App() {
  const [page, setPage] = useState<Page>('overview');
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [cash, setCash] = useState<CashResponse | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [ticketHistory, setTicketHistory] = useState<Record<number, AuditEvent[]>>({});
  const [runs, setRuns] = useState<Record<number, TicketRunResponse>>(storedRuns);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [runningIds, setRunningIds] = useState<number[]>([]);
  const [online, setOnline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [cashRefreshedAt, setCashRefreshedAt] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [decision, setDecision] = useState<{ approval: PendingApproval; kind: 'approve' | 'reject' } | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetPhrase, setResetPhrase] = useState('');
  const [newTicketOpen, setNewTicketOpen] = useState(false);
  const [creatingTicket, setCreatingTicket] = useState(false);
  const [newTicketError, setNewTicketError] = useState<string | null>(null);
  const runningRef = useRef(new Set<number>());
  const pollingRef = useRef(false);

  useEffect(() => {
    try { sessionStorage.setItem(RUN_STORAGE_KEY, JSON.stringify(runs)); } catch { /* Storage is optional. */ }
  }, [runs]);

  const refreshEvents = useCallback(async () => {
    if (pollingRef.current) return;
    pollingRef.current = true;
    try {
      const data = await api.events(200);
      setEvents(previous => JSON.stringify(previous) === JSON.stringify(data.events) ? previous : data.events);
      setOnline(true);
    } catch (cause) {
      setOnline(false);
      setError(cause instanceof Error ? cause.message : 'Activity could not be refreshed.');
    } finally { pollingRef.current = false; }
  }, []);

  const refreshAll = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    setRefreshing(true);
    const results = await Promise.allSettled([api.tickets(), api.cash(), api.events(200)]);
    const failures: string[] = [];
    if (results[0].status === 'fulfilled') setTickets(results[0].value.tickets);
    else failures.push(`Tickets: ${results[0].reason instanceof Error ? results[0].reason.message : 'request failed'}`);
    if (results[1].status === 'fulfilled') { setCash(results[1].value); setCashRefreshedAt(new Date()); }
    else failures.push(`Cash: ${results[1].reason instanceof Error ? results[1].reason.message : 'request failed'}`);
    if (results[2].status === 'fulfilled') setEvents(results[2].value.events);
    else failures.push(`Activity: ${results[2].reason instanceof Error ? results[2].reason.message : 'request failed'}`);
    setOnline(failures.length === 0);
    setError(failures.length ? failures.join(' · ') : null);
    if (failures.length === 0) setUpdatedAt(new Date());
    setRefreshing(false);
    setLoading(false);
  }, []);

  useEffect(() => { void refreshAll(true); }, [refreshAll]);
  useEffect(() => {
    const interval = window.setInterval(() => { void refreshEvents(); }, runningIds.length ? 1500 : 10000);
    return () => window.clearInterval(interval);
  }, [refreshEvents, runningIds.length]);
  useEffect(() => {
    const interval = window.setInterval(() => { void refreshAll(); }, 30000);
    return () => window.clearInterval(interval);
  }, [refreshAll]);

  const selectedRunning = selectedId !== null && runningIds.includes(selectedId);
  useEffect(() => {
    if (selectedId === null) return;
    let active = true;
    const refreshTicketHistory = async () => {
      try {
        const data = await api.events(500, selectedId);
        if (active) setTicketHistory(previous =>
          JSON.stringify(previous[selectedId]) === JSON.stringify(data.events)
            ? previous : { ...previous, [selectedId]: data.events }
        );
      } catch (cause) {
        if (active) setError(`Ticket activity: ${cause instanceof Error ? cause.message : 'request failed'}`);
      }
    };
    void refreshTicketHistory();
    const interval = window.setInterval(() => { void refreshTicketHistory(); }, selectedRunning ? 1500 : 10000);
    return () => { active = false; window.clearInterval(interval); };
  }, [selectedId, selectedRunning]);

  const selectedTicket = tickets.find(ticket => ticket.id === selectedId) ?? null;
  const visibleEvents = selectedId === null ? events : ticketHistory[selectedId] ?? [];
  const approvals = useMemo(() => Object.values(runs).flatMap(run => run.pending_approvals ?? []).filter(item => item.status === 'pending'), [runs]);
  const openCount = tickets.filter(ticket => ticket.status === 'open').length;
  const resolvedCount = tickets.filter(ticket => ticket.status === 'resolved').length;

  const selectTicket = (id: number | null) => {
    setSelectedId(id);
    if (id !== null) setPage('tickets');
  };

  const createTicket = async (input: CreateTicketInput) => {
    if (creatingTicket) return;
    setCreatingTicket(true);
    setNewTicketError(null);
    try {
      const created = await api.createTicket(input);
      setTickets(previous => [...previous.filter(ticket => ticket.id !== created.id), created].sort((a, b) => a.id - b.id));
      setSelectedId(created.id);
      setPage('tickets');
      setNewTicketOpen(false);
      setNotice(`Ticket #${created.id} created as Open. No agents have run.`);
      await refreshAll();
    } catch (cause) {
      setNewTicketError(cause instanceof Error ? cause.message : 'Ticket could not be created.');
    } finally {
      setCreatingTicket(false);
    }
  };

  const runTicket = async (ticketId: number) => {
    if (runningRef.current.has(ticketId)) return;
    runningRef.current.add(ticketId);
    setRunningIds(previous => [...previous, ticketId]);
    setSelectedId(ticketId);
    setPage('tickets');
    setError(null);
    setNotice(null);
    try {
      const result = await api.run(ticketId);
      setRuns(previous => ({ ...previous, [ticketId]: result }));
      setNotice(`Ticket #${ticketId} team run finished: ${result.status.replaceAll('_', ' ')}.`);
      await refreshAll();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The agent team could not start.');
      await refreshEvents();
    } finally {
      runningRef.current.delete(ticketId);
      setRunningIds(previous => previous.filter(id => id !== ticketId));
    }
  };

  const openDecision = async (approval: PendingApproval, kind: 'approve' | 'reject') => {
    if (kind === 'approve') {
      try { const nextCash = await api.cash(); setCash(nextCash); setCashRefreshedAt(new Date()); }
      catch (cause) { setError(cause instanceof Error ? cause.message : 'Cash could not be refreshed.'); return; }
    }
    setDecision({ approval, kind });
  };

  const confirmDecision = async (humanActor: string) => {
    if (!decision || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.decide(decision.approval.approval_id, decision.kind, humanActor);
      setRuns(previous => {
        const run = previous[decision.approval.ticket_id];
        if (!run) return previous;
        return { ...previous, [decision.approval.ticket_id]: {
          ...run,
          pending_approvals: run.pending_approvals.map(item => item.approval_id === decision.approval.approval_id ? { ...item, status: result.status as PendingApproval['status'] } : item),
        } };
      });
      setNotice(result.message);
      setDecision(null);
      await refreshAll();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'The approval decision failed.'); }
    finally { setBusy(false); }
  };

  const confirmReset = async () => {
    if (resetPhrase !== 'RESET' || busy || runningIds.length) return;
    setBusy(true);
    setError(null);
    try {
      const response = await api.reset();
      setRuns({});
      setSelectedId(null);
      sessionStorage.removeItem(RUN_STORAGE_KEY);
      setResetOpen(false);
      setResetPhrase('');
      setNotice(response.message);
      await refreshAll();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Shop reset failed.'); }
    finally { setBusy(false); }
  };

  return <div className="app-shell">
    <Sidebar page={page} onPage={setPage} online={online} />
    <div className="content-shell">
      <Header page={page} online={online} updatedAt={updatedAt} refreshing={refreshing} onRefresh={() => void refreshAll()} onReset={() => { setResetPhrase(''); setResetOpen(true); }} />
      {error ? <div className="feedback feedback--error" role="alert"><AlertCircle size={17} /><span>{error}</span><button type="button" onClick={() => setError(null)} aria-label="Dismiss error"><X size={16} /></button></div> : null}
      {notice ? <div className="feedback feedback--notice" role="status"><span>{notice}</span><button type="button" onClick={() => setNotice(null)} aria-label="Dismiss notice"><X size={16} /></button></div> : null}
      <div className="page-grid">
        <main className="workspace" id="main-content">
          {page === 'overview' ? <><MetricsStrip open={openCount} active={runningIds.length} approvals={approvals.length} resolved={resolvedCount} /><TicketTable tickets={tickets} selectedId={selectedId} onSelect={selectTicket} onRun={id => void runTicket(id)} onNewTicket={() => { setNewTicketError(null); setNewTicketOpen(true); }} runs={runs} runningIds={runningIds} events={events} loading={loading} /><AgentWorkspace events={visibleEvents} selectedId={selectedId} running={selectedRunning} /><ActivityTimeline events={visibleEvents} tickets={tickets} selectedId={selectedId} onSelectTicket={setSelectedId} running={runningIds.length > 0} /></> : null}
          {page === 'tickets' ? <><TicketTable tickets={tickets} selectedId={selectedId} onSelect={selectTicket} onRun={id => void runTicket(id)} onNewTicket={() => { setNewTicketError(null); setNewTicketOpen(true); }} runs={runs} runningIds={runningIds} events={events} loading={loading} /><TicketDetails ticket={selectedTicket} run={selectedId !== null ? runs[selectedId] : undefined} running={selectedRunning} onRun={() => selectedId !== null && void runTicket(selectedId)} onApprovals={() => setPage('approvals')} /><AgentWorkspace events={visibleEvents} selectedId={selectedId} running={selectedRunning} /><ActivityTimeline events={visibleEvents} tickets={tickets} selectedId={selectedId} onSelectTicket={setSelectedId} running={selectedRunning} /></> : null}
          {page === 'activity' ? <><div className="page-intro"><span className="eyebrow">Recorded operations</span><p>Every entry comes from the backend audit trail. Expand a row for arguments and results.</p></div><ActivityTimeline events={visibleEvents} tickets={tickets} selectedId={selectedId} onSelectTicket={setSelectedId} running={selectedRunning} /><AgentWorkspace events={visibleEvents} selectedId={selectedId} running={selectedRunning} /></> : null}
          {page === 'approvals' ? <><div className="page-intro"><span className="eyebrow">Decision desk</span><p>Review agent proposals before any shop balance changes.</p></div><ApprovalQueue approvals={approvals} onApprove={item => void openDecision(item, 'approve')} onReject={item => void openDecision(item, 'reject')} busy={busy} />{approvals.length ? <button type="button" className="inline-link" onClick={() => setPage('tickets')}>View related ticket work <ArrowUpRight size={15} /></button> : null}</> : null}
        </main>
        <aside className="information-panel" aria-label="Financial information"><CashBalance cash={cash} refreshedAt={cashRefreshedAt} loading={loading} /><ApprovalQueue approvals={approvals} onApprove={item => void openDecision(item, 'approve')} onReject={item => void openDecision(item, 'reject')} busy={busy} compact /><div className="panel-foot"><span className="eyebrow">Source</span><p>Live data from Campus Customs working database via the operations API.</p><Status value={online ? 'completed' : 'blocked'}>{online ? 'Backend connected' : 'Backend unavailable'}</Status></div></aside>
      </div>
    </div>
    {decision ? <DecisionModal approval={decision.approval} decision={decision.kind} cash={cash} busy={busy} onClose={() => { if (!busy) setDecision(null); }} onConfirm={actor => void confirmDecision(actor)} /> : null}
    {newTicketOpen ? <NewTicketModal busy={creatingTicket} error={newTicketError} onClose={() => { if (!creatingTicket) setNewTicketOpen(false); }} onCreate={createTicket} /> : null}
    {resetOpen ? <Modal title="Reset shop data" onClose={() => { if (!busy) setResetOpen(false); }}><div className="modal__body"><p className="modal__intro">Restore the working database from the original copy. This clears current run and approval state. Historical audit activity stays recorded.</p><label className="form-field">Type RESET to confirm<input autoFocus value={resetPhrase} onChange={event => setResetPhrase(event.target.value)} autoComplete="off" spellCheck={false} /></label></div><div className="modal__foot"><button type="button" className="button button--outline" onClick={() => setResetOpen(false)} disabled={busy}>Cancel</button><button type="button" className="button button--black" onClick={() => void confirmReset()} disabled={busy || resetPhrase !== 'RESET' || runningIds.length > 0}>{busy ? 'Resetting...' : 'Reset Shop'}</button></div></Modal> : null}
  </div>;
}

export default App;
