import { ArrowUpRight } from 'lucide-react';
import type { PendingApproval } from '../../api/client';
import { money } from '../../api/client';
import { Status } from '../common/Status';

export function ApprovalQueue({ approvals, onApprove, onReject, busy, compact = false }: {
  approvals: PendingApproval[]; onApprove: (approval: PendingApproval) => void;
  onReject: (approval: PendingApproval) => void; busy: boolean; compact?: boolean;
}) {
  return <section className={`approval-queue${compact ? ' approval-queue--compact' : ''}`} aria-labelledby={compact ? 'sidebar-approvals' : 'main-approvals'}>
    <div className="approval-heading"><div><span className="eyebrow">Human decisions</span><h2 id={compact ? 'sidebar-approvals' : 'main-approvals'}>Pending approvals <span className="heading-count">{approvals.length}</span></h2></div>{!compact ? <ArrowUpRight size={17} aria-hidden="true" /> : null}</div>
    {approvals.length === 0 ? <p className="approval-empty">No proposals awaiting review.</p> : <div className="approval-list">{approvals.map(item =>
      <article className="approval-item" key={item.approval_id}>
        <div className="approval-item__top"><span className="mono">TICKET #{item.ticket_id}</span><Status value="awaiting">Pending</Status></div>
        <h3>{item.action}</h3><p>{item.details}</p>
        <span className="approval-item__kind">{item.action_type.replaceAll('_', ' ')}</span>
        <div className="approval-item__amount">{item.amount === null ? 'Amount not specified' : money(item.amount)}</div>
        {item.action_type !== 'payment' ? <p className="approval-item__note">This action has no executable payment workflow. You can reject it or review it with the team.</p> : null}
        <div className="approval-item__actions"><button type="button" className="button button--black" onClick={() => onApprove(item)} disabled={busy || item.action_type !== 'payment'}>Approve</button><button type="button" className="button button--outline" onClick={() => onReject(item)} disabled={busy}>Reject</button></div>
      </article>
    )}</div>}
  </section>;
}
