import { useState, type FormEvent } from 'react';
import type { CashResponse, PendingApproval } from '../../api/client';
import { money } from '../../api/client';
import { Modal } from '../common/Modal';

export function DecisionModal({ approval, decision, cash, busy, onClose, onConfirm }: {
  approval: PendingApproval; decision: 'approve' | 'reject'; cash: CashResponse | null;
  busy: boolean; onClose: () => void; onConfirm: (humanActor: string) => void;
}) {
  const [actor, setActor] = useState('');
  const isApproval = decision === 'approve';
  const submit = (event: FormEvent) => { event.preventDefault(); if (actor.trim()) onConfirm(actor.trim()); };
  return <Modal title={isApproval ? 'Confirm payment' : 'Reject proposal'} onClose={onClose}>
    <form onSubmit={submit}>
      <div className="modal__body"><p className="modal__intro">{isApproval ? 'Review the recorded proposal before changing the shop’s cash balance.' : 'Rejecting this proposal leaves the shop’s cash unchanged.'}</p>
        <dl className="confirmation-facts"><div><dt>Ticket</dt><dd className="mono">#{approval.ticket_id}</dd></div><div><dt>Purpose</dt><dd>{approval.action}</dd></div><div><dt>Amount</dt><dd className="mono">{approval.amount !== null ? money(approval.amount) : 'Not specified'}</dd></div><div><dt>Current checking balance</dt><dd className="mono">{cash ? money(cash.checking_balance) : 'Unavailable'}</dd></div></dl>
        <label className="form-field">Your name <input autoFocus value={actor} onChange={event => setActor(event.target.value)} required maxLength={100} placeholder="Name of approving person" autoComplete="name" /></label>
        {isApproval ? <p className="modal__caution">Confirming sends an explicit human approval. The backend will recheck cash and payment status before making any change.</p> : null}
      </div>
      <div className="modal__foot"><button type="button" className="button button--outline" onClick={onClose} disabled={busy}>Cancel</button><button type="submit" className="button button--black" disabled={busy || !actor.trim() || (isApproval && (cash === null || approval.amount === null))}>{busy ? <><span className="spinner" aria-hidden="true" /> Processing...</> : isApproval ? 'Confirm payment' : 'Reject proposal'}</button></div>
    </form>
  </Modal>;
}
