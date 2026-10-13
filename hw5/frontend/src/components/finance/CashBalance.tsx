import { ArrowDownRight } from 'lucide-react';
import type { CashResponse } from '../../api/client';
import { money } from '../../api/client';

export function CashBalance({ cash, refreshedAt, loading }: { cash: CashResponse | null; refreshedAt: Date | null; loading: boolean }) {
  return <section className="finance-balance" aria-labelledby="balance-heading">
    <div className="finance-section-head"><span className="eyebrow">Finances</span><ArrowDownRight size={16} aria-hidden="true" /></div>
    <h2 id="balance-heading" className="eyebrow">Checking balance</h2>
    <div className="balance-number" aria-live="polite">{cash ? money(cash.checking_balance) : loading ? <span className="balance-skeleton" /> : '—'}</div>
    <p className="finance-caption">{cash ? `Cash accounts · ${refreshedAt ? `Refreshed ${refreshedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Live data'}` : 'Awaiting backend data'}</p>
  </section>;
}
