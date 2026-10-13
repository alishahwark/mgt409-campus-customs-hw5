import { useState, type FormEvent } from 'react';
import type { CreateTicketInput } from '../../api/client';
import { Modal } from '../common/Modal';

export function NewTicketModal({ busy, error, onClose, onCreate }: {
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onCreate: (input: CreateTicketInput) => Promise<void>;
}) {
  const [subject, setSubject] = useState('');
  const [description, setDescription] = useState('');
  const [validation, setValidation] = useState<string | null>(null);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const input = { subject: subject.trim(), description: description.trim() };
    if (!input.subject || !input.description) {
      setValidation('Enter both a subject and a description.');
      return;
    }
    setValidation(null);
    void onCreate(input);
  };

  return <Modal title="New ticket" onClose={onClose}>
    <form onSubmit={submit}>
      <div className="modal__body ticket-form">
        <p className="modal__intro">Create an open desk ticket. The agent team runs only when you select Run Ticket.</p>
        <label className="form-field">Subject
          <input autoFocus data-initial-focus value={subject} onChange={event => { setSubject(event.target.value); setValidation(null); }} maxLength={120} required placeholder="What needs attention?" />
        </label>
        <label className="form-field">Description
          <textarea value={description} onChange={event => { setDescription(event.target.value); setValidation(null); }} maxLength={2000} required rows={5} placeholder="Describe the request and any known details." />
        </label>
        {validation || error ? <p className="ticket-form__error" role="alert">{validation || error}</p> : null}
      </div>
      <div className="modal__foot">
        <button type="button" className="button button--outline" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="submit" className="button button--black" disabled={busy}>{busy ? 'Creating...' : 'Create Ticket'}</button>
      </div>
    </form>
  </Modal>;
}
