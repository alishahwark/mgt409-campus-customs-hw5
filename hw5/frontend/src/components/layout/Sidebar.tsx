import { Activity, CheckCheck, LayoutGrid, ListTodo, type LucideIcon } from 'lucide-react';

export type Page = 'overview' | 'tickets' | 'activity' | 'approvals';
const items: { id: Page; label: string; icon: LucideIcon }[] = [
  { id: 'overview', label: 'Overview', icon: LayoutGrid },
  { id: 'tickets', label: 'Tickets', icon: ListTodo },
  { id: 'activity', label: 'Agent Activity', icon: Activity },
  { id: 'approvals', label: 'Approvals', icon: CheckCheck },
];

export function Sidebar({ page, onPage, online }: { page: Page; onPage: (page: Page) => void; online: boolean }) {
  return <aside className="sidebar">
    <div className="sidebar__brand"><span className="brand-symbol" aria-hidden="true"><span /><span /><span /><span /></span><div><strong>Campus<br />Customs</strong><span className="brand-meta">OPERATIONS / 01</span></div></div>
    <nav className="sidebar__nav" aria-label="Primary navigation">{items.map(({ id, label, icon: Icon }) =>
      <button key={id} type="button" className={`nav-item${page === id ? ' nav-item--active' : ''}`} aria-label={label} aria-current={page === id ? 'page' : undefined} onClick={() => onPage(id)}><Icon size={17} strokeWidth={1.8} aria-hidden="true" /><span>{label}</span></button>
    )}</nav>
    <div className="sidebar__foot"><span className={`connection-dot${online ? ' connection-dot--online' : ''}`} aria-hidden="true" /><span>{online ? 'SYSTEM ONLINE' : 'SYSTEM OFFLINE'}</span></div>
  </aside>;
}
